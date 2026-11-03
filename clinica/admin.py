from collections import Counter

from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import (
    Calificare, GradProfesional, Notificare, Pacient, Profesie, Sedinta, Specialist, Utilizator,
)

# Utilizator folosește administrarea standard Django (hash parolă, permisiuni etc.)
admin.site.register(Utilizator, UserAdmin)


# ---------------------------------------------------------------- persoane

@admin.register(Pacient)
class PacientAdmin(admin.ModelAdmin):
    list_display = ['nume', 'prenume', 'data_nasterii', 'email', 'utilizator']
    search_fields = ['nume', 'prenume', 'email']
    list_filter = ['sex']
    readonly_fields = ['data_inregistrare']
    autocomplete_fields = ['utilizator']


class CalificareInline(admin.TabularInline):
    """
    Calificările specialistului, doar pentru vizualizare.
    Se adaugă și se modifică din pagina „Calificări”, unde există acțiunile
    de verificare, activare și dezactivare.
    """
    model = Calificare
    extra = 0
    can_delete = False
    show_change_link = True
    fields = ['grad', 'domeniu', 'nr_document', 'data_expirare', 'stare', 'verificata']
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Specialist)
class SpecialistAdmin(admin.ModelAdmin):
    list_display = ['nume', 'prenume', 'email', 'accepta_pacienti_noi']
    search_fields = ['nume', 'prenume', 'email']
    list_filter = ['accepta_pacienti_noi', 'calificari__grad__profesie']
    readonly_fields = ['data_inregistrare']
    autocomplete_fields = ['utilizator']
    inlines = [CalificareInline]


# ---------------------------------------------------------------- profesii

class GradProfesionalInline(admin.TabularInline):
    """Gradele se editează direct în pagina profesiei."""
    model = GradProfesional
    extra = 0


@admin.register(Profesie)
class ProfesieAdmin(admin.ModelAdmin):
    list_display = ['nume', 'organism_emitent', 'grade_ierarhice', 'poate_prescrie', 'poate_diagnostica']
    inlines = [GradProfesionalInline]


@admin.register(GradProfesional)
class GradProfesionalAdmin(admin.ModelAdmin):
    list_display = ['profesie', 'nume', 'ordine', 'poate_superviza']
    list_filter = ['profesie']
    search_fields = ['nume', 'profesie__nume']


# ---------------------------------------------------------------- calificări

def _actiune_dezactivare(motiv):
    """Construiește câte o acțiune de dezactivare pentru fiecare motiv."""

    def actiune(modeladmin, request, queryset):
        for c in queryset:
            try:
                anulate = c.dezactiveaza(request.user, motiv)
            except ValidationError as e:
                modeladmin.message_user(request, f'{c}: {" ".join(e.messages)}', messages.ERROR)
            else:
                modeladmin.message_user(
                    request, f'{c}: dezactivată. Ședințe viitoare anulate și pacienți notificați: {anulate}.',
                    messages.SUCCESS,
                )

    actiune.__name__ = f'dezactiveaza_{motiv.value}'
    return admin.action(
        description=f'Dezactivează – {motiv.label.lower()}', permissions=['gestioneaza'],
    )(actiune)


@admin.register(Calificare)
class CalificareAdmin(admin.ModelAdmin):
    list_display = ['specialist', 'grad', 'domeniu', 'nr_document', 'stare', 'verificata', 'data_expirare']
    list_filter = ['activa', 'verificata', 'motiv_dezactivare', 'grad__profesie']
    search_fields = ['specialist__nume', 'specialist__prenume', 'nr_document', 'domeniu']
    autocomplete_fields = ['specialist', 'grad']
    actions = [
        'marcheaza_verificata', 'anuleaza_verificarea', 'activeaza',
        *[_actiune_dezactivare(m) for m in Calificare.MotivDezactivare if m != Calificare.MotivDezactivare.PROMOVARE],
    ]

    _CAMPURI_ADMINISTRARE = ['verificata', 'verificata_de', 'verificata_la',
                             'motiv_dezactivare', 'dezactivata_de', 'dezactivata_la']

    def get_readonly_fields(self, request, obj=None):
        # „activa” se alege doar la adăugare; după aceea se schimbă doar prin acțiuni
        return self._CAMPURI_ADMINISTRARE + (['activa'] if obj else [])

    def has_gestioneaza_permission(self, request):
        return request.user.has_perm('clinica.gestioneaza_calificari')

    @admin.action(description='Marchează ca verificate (confirmate în registrul oficial)',
                  permissions=['gestioneaza'])
    def marcheaza_verificata(self, request, queryset):
        n = queryset.update(verificata=True, verificata_de=request.user, verificata_la=timezone.now())
        self.message_user(request, f'{n} calificări marcate ca verificate.')

    @admin.action(description='Anulează verificarea', permissions=['gestioneaza'])
    def anuleaza_verificarea(self, request, queryset):
        n = queryset.update(verificata=False, verificata_de=None, verificata_la=None)
        self.message_user(request, f'Verificarea a fost anulată pentru {n} calificări.')

    @admin.action(description='Activează (înlocuiește documentul activ și mută programările)',
                  permissions=['gestioneaza'])
    def activeaza(self, request, queryset):
        grupuri = Counter(
            (c.specialist_id, c.grad.profesie_id, c.domeniu.lower()) for c in queryset.select_related('grad')
        )
        if any(n > 1 for n in grupuri.values()):
            self.message_user(
                request,
                'Ai selectat mai multe documente pentru aceeași persoană, profesie și domeniu. '
                'Activează-l doar pe cel valabil.',
                messages.ERROR,
            )
            return
        for c in queryset:
            try:
                mutate = c.activeaza(request.user)
            except ValidationError as e:
                self.message_user(request, f'{c}: {" ".join(e.messages)}', messages.ERROR)
            else:
                self.message_user(
                    request, f'{c}: activată. Ședințe viitoare mutate pe noul document: {mutate}.',
                    messages.SUCCESS,
                )

    def get_search_results(self, request, queryset, search_term):
        queryset, may_have_duplicates = super().get_search_results(request, queryset, search_term)
        # în căutarea din formularul de ședință apar doar calificările utilizabile
        if request.GET.get('model_name') == 'sedinta':
            queryset = queryset.filter(activa=True, verificata=True)
        return queryset, may_have_duplicates


# ---------------------------------------------------------------- ședințe

@admin.register(Sedinta)
class SedintaAdmin(admin.ModelAdmin):
    list_display = ['data_ora', 'pacient', 'calificare', 'status', 'pret']
    list_filter = ['status', 'calificare__grad__profesie']
    search_fields = ['pacient__nume', 'pacient__prenume', 'calificare__specialist__nume']
    date_hierarchy = 'data_ora'
    autocomplete_fields = ['pacient', 'calificare']
    readonly_fields = ['anulata_la', 'creata_la']


# ---------------------------------------------------------------- notificări

class AreContFilter(admin.SimpleListFilter):
    title = 'pacientul are cont'
    parameter_name = 'are_cont'

    def lookups(self, request, model_admin):
        return [('da', 'Da'), ('nu', 'Nu – de contactat telefonic')]

    def queryset(self, request, queryset):
        if self.value() == 'da':
            return queryset.filter(pacient__utilizator__isnull=False)
        if self.value() == 'nu':
            return queryset.filter(pacient__utilizator__isnull=True)
        return queryset


class CititaFilter(admin.SimpleListFilter):
    title = 'citită / transmisă'
    parameter_name = 'citita'

    def lookups(self, request, model_admin):
        return [('da', 'Da'), ('nu', 'Nu')]

    def queryset(self, request, queryset):
        if self.value() == 'da':
            return queryset.filter(citita_la__isnull=False)
        if self.value() == 'nu':
            return queryset.filter(citita_la__isnull=True)
        return queryset


@admin.register(Notificare)
class NotificareAdmin(admin.ModelAdmin):
    list_display = ['creata_la', 'pacient', 'tip', 'are_cont', 'telefon_contact', 'citita_la']
    list_filter = ['tip', AreContFilter, CititaFilter]
    list_select_related = ['pacient', 'pacient__utilizator']
    search_fields = ['pacient__nume', 'pacient__prenume', 'mesaj']
    autocomplete_fields = ['pacient', 'sedinta']
    readonly_fields = ['creata_la']
    actions = ['marcheaza_citita']

    @admin.display(description='are cont', boolean=True)
    def are_cont(self, obj):
        return obj.pacient.utilizator_id is not None

    @admin.display(description='telefon')
    def telefon_contact(self, obj):
        p = obj.pacient
        if p.telefon:
            return p.telefon
        if p.contact_urgenta_telefon:
            return f'{p.contact_urgenta_telefon} ({p.contact_urgenta_nume or "contact de urgență"})'
        return '–'

    @admin.action(description='Marchează ca citite / transmise telefonic')
    def marcheaza_citita(self, request, queryset):
        n = queryset.filter(citita_la__isnull=True).update(citita_la=timezone.now())
        self.message_user(request, f'{n} notificări marcate ca citite / transmise.')
