from datetime import timedelta
from functools import wraps

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.views import redirect_to_login
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .forms import (
    AlegePacientForm, InregistrarePacientForm, PacientTelefonicForm, ProgramFormSet,
    SedintaTelefonForm, SpecialistProfilForm,
)
from django.core.exceptions import ValidationError

from .models import Calificare, Pacient, Sedinta, Specialist, Utilizator
from .servicii import comaseaza_program, leaga_cont, poate_fi_legat


# ---------------------------------------------------------------- roluri

def rol(user):
    """'admin' | 'specialist' | 'asistent' | 'pacient' | None (cont fără fișă asociată)."""
    if user.is_superuser or user.is_staff:
        return 'admin'
    if hasattr(user, 'specialist'):
        return 'specialist'
    if hasattr(user, 'asistent'):
        return 'asistent'
    if hasattr(user, 'pacient'):
        return 'pacient'
    return None


def rol_necesar(*roluri):
    """Permite accesul doar rolurilor date; altfel trimite utilizatorul în zona lui."""
    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if rol(request.user) not in roluri:
                return redirect('home')
            return view(request, *args, **kwargs)
        return wrapper
    return decorator


def _calificari_valabile():
    """Calificările pe care un pacient are voie să le vadă: active, verificate, neexpirate."""
    return Calificare.valabile()


def home(request):
    """Trimite fiecare utilizator în interfața rolului său."""
    if not request.user.is_authenticated:
        return redirect('login')
    destinatii = {'admin': 'admin:index', 'specialist': 'panou_specialist',
                  'asistent': 'panou_asistent', 'pacient': 'panou_pacient'}
    destinatie = destinatii.get(rol(request.user))
    if destinatie is None:
        return render(request, 'clinica/fara_rol.html')
    return redirect(destinatie)


def inregistrare(request):
    if request.user.is_authenticated:
        return redirect('home')
    form = InregistrarePacientForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        login(request, form.save())
        return redirect('home')
    return render(request, 'registration/inregistrare.html', {'form': form})


# ---------------------------------------------------------------- specialist

@rol_necesar('specialist')
def panou_specialist(request):
    specialist = request.user.specialist
    sedinte = (
        Sedinta.objects
        .filter(calificare__specialist=specialist, status=Sedinta.Status.PROGRAMATA,
                data_ora__gte=timezone.now())
        .select_related('pacient', 'calificare__grad__profesie')
        .order_by('data_ora')
    )
    return render(request, 'clinica/specialist/panou.html', {
        'specialist': specialist,
        'sedinte': sedinte,
        'calificari': specialist.calificari.select_related('grad__profesie'),
        'program': specialist.program.all(),
    })


def _sedinte_specialist(specialist):
    return (
        Sedinta.objects.filter(calificare__specialist=specialist)
        .select_related('pacient', 'calificare__grad__profesie')
    )


@rol_necesar('specialist')
def sedinte_viitoare(request):
    sedinte = _sedinte_specialist(request.user.specialist).filter(
        status=Sedinta.Status.PROGRAMATA, data_ora__gte=timezone.now(),
    ).order_by('data_ora')
    return render(request, 'clinica/specialist/sedinte.html', {
        'titlu': 'Ședințe viitoare', 'sedinte': sedinte, 'viitoare': True,
        'gol': 'Nu ai ședințe programate.',
    })


@rol_necesar('specialist')
def istoric_sedinte(request):
    """Tot ce nu mai e programat în viitor: finalizate, anulate, neprezentări, trecute."""
    sedinte = _sedinte_specialist(request.user.specialist).exclude(
        status=Sedinta.Status.PROGRAMATA, data_ora__gte=timezone.now(),
    ).order_by('-data_ora')
    status = request.GET.get('status')
    if status in Sedinta.Status.values:
        sedinte = sedinte.filter(status=status)
    return render(request, 'clinica/specialist/sedinte.html', {
        'titlu': 'Istoric ședințe', 'sedinte': sedinte, 'viitoare': False,
        'statusuri': Sedinta.Status.choices, 'status_ales': status,
        'gol': 'Nu există ședințe în istoric.',
    })


def _fara_calificari(request, specialist):
    """True (și mesaj) dacă specialistul nu are nicio calificare cu care să programeze."""
    if Calificare.valabile().filter(specialist=specialist).exists():
        return False
    messages.error(request, 'Nu ai nicio calificare activă și verificată, deci nu poți programa ședințe.')
    return True


@rol_necesar('specialist')
def pacient_nou(request):
    """Pacient nou, dictat telefonic: se creează fișa (fără cont) și prima ședință."""
    specialist = request.user.specialist
    if _fara_calificari(request, specialist):
        return redirect('panou_specialist')
    pacient_form = PacientTelefonicForm(request.POST or None)
    sedinta_form = SedintaTelefonForm(request.POST or None, specialist=specialist)
    if request.method == 'POST' and pacient_form.is_valid() and sedinta_form.is_valid():
        with transaction.atomic():
            pacient = pacient_form.save()
            sedinta = sedinta_form.save(commit=False)
            sedinta.pacient = pacient
            sedinta.save()
        messages.success(request, f'Pacientul {pacient} a fost adăugat și ședința a fost programată.')
        return redirect('sedinte_viitoare')
    return render(request, 'clinica/programare.html', {
        'titlu': 'Pacient nou (fără cont)', 'pacient_form': pacient_form, 'sedinta_form': sedinta_form,
        'inapoi_url': reverse('panou_specialist'),
    })


@rol_necesar('specialist')
def programeaza_sedinta(request):
    """Ședință nouă pentru un pacient cu care specialistul a mai lucrat."""
    specialist = request.user.specialist
    if _fara_calificari(request, specialist):
        return redirect('panou_specialist')
    alege_form = AlegePacientForm(request.POST or None, specialist=specialist)
    sedinta_form = SedintaTelefonForm(request.POST or None, specialist=specialist)
    if request.method == 'POST' and alege_form.is_valid() and sedinta_form.is_valid():
        sedinta = sedinta_form.save(commit=False)
        sedinta.pacient = alege_form.cleaned_data['pacient']
        sedinta.save()
        messages.success(request, 'Ședința a fost programată.')
        return redirect('sedinte_viitoare')
    return render(request, 'clinica/programare.html', {
        'titlu': 'Programează o ședință', 'pacient_form': alege_form, 'sedinta_form': sedinta_form,
        'inapoi_url': reverse('panou_specialist'),
    })


@rol_necesar('specialist')
def profil_specialist(request):
    specialist = request.user.specialist
    form = SpecialistProfilForm(request.POST or None, instance=specialist)
    program = ProgramFormSet(request.POST or None, instance=specialist)
    if request.method == 'POST' and form.is_valid() and program.is_valid():
        form.save()
        program.save()
        comasate = comaseaza_program(specialist)
        messages.success(request, 'Modificările au fost salvate.')
        if comasate:
            messages.info(request, 'Intervalele care se suprapuneau sau se atingeau au fost comasate.')
        return redirect('panou_specialist')
    return render(request, 'clinica/specialist/profil.html', {'form': form, 'program': program})


# ---------------------------------------------------------------- pacient

@rol_necesar('pacient')
def panou_pacient(request):
    return render(request, 'clinica/pacient/panou.html', {'pacient': request.user.pacient})


@rol_necesar('pacient')
def sedintele_mele(request):
    """Istoricul (primul) și ședințele viitoare (al doilea), pentru pacientul autentificat."""
    sedinte = (
        Sedinta.objects.filter(pacient=request.user.pacient)
        .select_related('calificare__specialist', 'calificare__grad__profesie')
    )
    viitoare = sedinte.filter(status=Sedinta.Status.PROGRAMATA, data_ora__gte=timezone.now())
    return render(request, 'clinica/pacient/sedinte.html', {
        'istoric': sedinte.exclude(pk__in=viitoare.values('pk')).order_by('-data_ora'),
        'viitoare': viitoare.order_by('data_ora'),
    })


@rol_necesar('pacient')
def terapeuti(request):
    calificari = Prefetch(
        'calificari', queryset=_calificari_valabile().select_related('grad__profesie'),
        to_attr='calificari_valabile',
    )
    specialisti = (
        Specialist.objects
        .filter(calificari__in=_calificari_valabile()).distinct()
        .prefetch_related(calificari)
    )
    return render(request, 'clinica/terapeuti.html', {'specialisti': specialisti})


@rol_necesar('pacient')
def terapeut_detaliu(request, pk):
    specialist = get_object_or_404(
        Specialist.objects.filter(calificari__in=_calificari_valabile()).distinct(), pk=pk,
    )
    return render(request, 'clinica/terapeut_detaliu.html', {
        'specialist': specialist,
        'calificari': _calificari_valabile().filter(specialist=specialist).select_related('grad__profesie'),
        'program': specialist.program.all(),
    })


# ---------------------------------------------------------------- asistent
# Acces doar în citire. Notele confidențiale ale ședințelor nu sunt afișate niciodată.

def _pagina(request, queryset, pe_pagina=30):
    return Paginator(queryset, pe_pagina).get_page(request.GET.get('pagina'))


def _fara_pagina(request):
    """Parametrii GET fără numărul paginii, pentru linkurile de paginare."""
    params = request.GET.copy()
    params.pop('pagina', None)
    return params.urlencode()


@rol_necesar('asistent')
def panou_asistent(request):
    return render(request, 'clinica/asistent/panou.html', {
        'asistent': request.user.asistent,
        'nr_pacienti': Pacient.objects.count(),
        'nr_fara_cont': Pacient.objects.filter(utilizator__isnull=True).count(),
        'nr_utilizatori': Utilizator.objects.count(),
        'nr_viitoare': Sedinta.objects.filter(
            status=Sedinta.Status.PROGRAMATA, data_ora__gte=timezone.now()).count(),
    })


@rol_necesar('asistent')
def asistent_pacienti(request):
    pacienti = Pacient.objects.select_related('utilizator')
    q = request.GET.get('q', '').strip()
    if q:
        for cuvant in q.split():
            pacienti = pacienti.filter(
                Q(nume__icontains=cuvant) | Q(prenume__icontains=cuvant) | Q(email__icontains=cuvant)
                | Q(telefon__icontains=cuvant)
            )
    cont = request.GET.get('cont')
    if cont == 'da':
        pacienti = pacienti.filter(utilizator__isnull=False)
    elif cont == 'nu':
        pacienti = pacienti.filter(utilizator__isnull=True)
    return render(request, 'clinica/asistent/pacienti.html', {
        'pagina': _pagina(request, pacienti), 'q': q, 'cont': cont, 'param': _fara_pagina(request),
    })


@rol_necesar('asistent')
def asistent_leaga_alege(request, pk):
    """Pasul 1: pentru o fișă fără cont, asistenta caută contul de legat."""
    fisa = get_object_or_404(Pacient, pk=pk, utilizator__isnull=True)
    conturi = Utilizator.objects.filter(
        is_staff=False, is_superuser=False, specialist__isnull=True, asistent__isnull=True,
    ).order_by('username')
    q = request.GET.get('q', '').strip()
    for cuvant in q.split():
        conturi = conturi.filter(
            Q(username__icontains=cuvant) | Q(first_name__icontains=cuvant)
            | Q(last_name__icontains=cuvant) | Q(email__icontains=cuvant)
        )
    return render(request, 'clinica/asistent/leaga_alege.html', {
        'fisa': fisa, 'q': q, 'conturi': conturi[:20],
    })


@rol_necesar('asistent')
def asistent_leaga_confirma(request, pk, utilizator_pk):
    """Pasul 2: rezumatul celor două fișe, apoi comasarea la confirmare (POST)."""
    fisa = get_object_or_404(Pacient, pk=pk, utilizator__isnull=True)
    utilizator = get_object_or_404(Utilizator, pk=utilizator_pk)
    if not poate_fi_legat(utilizator):
        messages.error(request, 'Acest cont nu este un cont de pacient.')
        return redirect('asistent_leaga_alege', pk=fisa.pk)
    alta = Pacient.objects.filter(utilizator=utilizator).first()

    if request.method == 'POST':
        try:
            mutate = leaga_cont(fisa, utilizator, de_catre=request.user)
        except ValidationError as e:
            messages.error(request, ' '.join(e.messages))
        else:
            messages.success(
                request, f'Fișa {fisa} a fost legată de contul {utilizator.username}. '
                         f'Înregistrări comasate din fișa contului: {mutate}.',
            )
            return redirect('asistent_pacienti')

    diferente = bool(alta) and (
        (alta.nume.lower(), alta.prenume.lower(), alta.data_nasterii)
        != (fisa.nume.lower(), fisa.prenume.lower(), fisa.data_nasterii)
    )
    return render(request, 'clinica/asistent/leaga_confirma.html', {
        'fisa': fisa, 'utilizator': utilizator, 'alta': alta, 'diferente': diferente,
        'sedinte_fisa': fisa.sedinte.count(),
        'sedinte_alta': alta.sedinte.count() if alta else 0,
    })


@rol_necesar('asistent')
def asistent_pacient_nou(request):
    """Persoană care sună pentru prima dată: se creează fișa (fără cont), apoi se programează."""
    form = PacientTelefonicForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        pacient = form.save()
        messages.success(request, f'Fișa pentru {pacient} a fost creată. Programează acum prima ședință.')
        return redirect('asistent_programeaza', pk=pacient.pk)
    return render(request, 'clinica/programare.html', {
        'titlu': 'Pacient nou (fără cont)', 'pacient_form': form, 'sedinta_form': None,
        'inapoi_url': reverse('asistent_pacienti'),
    })


@rol_necesar('asistent')
def asistent_programeaza(request, pk):
    """Programează o ședință viitoare pentru un pacient, la orice specialist."""
    pacient = get_object_or_404(Pacient, pk=pk)
    form = SedintaTelefonForm(request.POST or None, pacient=pacient)
    if request.method == 'POST' and form.is_valid():
        sedinta = form.save(commit=False)
        sedinta.pacient = pacient
        sedinta.save()
        messages.success(request, f'Ședința pentru {pacient} a fost programată.')
        return redirect('asistent_sedinte')
    return render(request, 'clinica/programare.html', {
        'titlu': f'Programează o ședință: {pacient}', 'pacient_form': None, 'sedinta_form': form,
        'inapoi_url': reverse('asistent_pacienti'),
        'orar_url': reverse('asistent_orar', args=[0]),  # 0 = loc rezervat pentru calificarea aleasă
    })


@rol_necesar('asistent')
def asistent_orar(request, calificare_pk):
    """Fragment HTML cu programul specialistului și intervalele deja ocupate (următoarele 30 de zile)."""
    calificare = get_object_or_404(
        Calificare.valabile().select_related('specialist', 'grad__profesie'), pk=calificare_pk,
    )
    specialist = calificare.specialist
    acum = timezone.now()
    ocupate = [
        (s.data_ora, s.data_ora + timedelta(minutes=s.durata_minute))
        for s in Sedinta.objects.filter(
            calificare__specialist=specialist, status=Sedinta.Status.PROGRAMATA,
            data_ora__gte=acum, data_ora__lt=acum + timedelta(days=30),
        ).order_by('data_ora')
    ]
    return render(request, 'clinica/asistent/_orar.html', {
        'specialist': specialist, 'program': specialist.program.all(), 'ocupate': ocupate,
    })


@rol_necesar('asistent')
def asistent_anuleaza(request, pk):
    """Anulează o ședință viitoare (ex: pacientul a sunat). Rămâne în istoric, cu motiv și dată."""
    sedinta = get_object_or_404(
        Sedinta.objects.select_related('pacient', 'calificare__specialist'), pk=pk,
    )
    if sedinta.status != Sedinta.Status.PROGRAMATA or sedinta.data_ora < timezone.now():
        messages.error(request, 'Doar ședințele programate în viitor pot fi anulate.')
        return redirect('asistent_sedinte')
    if request.method == 'POST':
        motiv = request.POST.get('motiv', '').strip() or 'Anulată la cererea pacientului.'
        sedinta.status = Sedinta.Status.ANULATA
        sedinta.motiv_anulare = motiv[:255]
        sedinta.save()
        messages.success(request, 'Ședința a fost anulată.')
        return redirect('asistent_sedinte')
    return render(request, 'clinica/asistent/anuleaza.html', {'sedinta': sedinta})


@rol_necesar('asistent')
def asistent_utilizatori(request):
    utilizatori = Utilizator.objects.select_related('pacient', 'specialist', 'asistent').order_by('username')
    q = request.GET.get('q', '').strip()
    if q:
        for cuvant in q.split():
            utilizatori = utilizatori.filter(
                Q(username__icontains=cuvant) | Q(first_name__icontains=cuvant)
                | Q(last_name__icontains=cuvant) | Q(email__icontains=cuvant)
            )
    pagina = _pagina(request, utilizatori)
    etichete = {'admin': 'Administrator', 'specialist': 'Specialist', 'asistent': 'Asistent',
                'pacient': 'Pacient', None: 'Fără fișă'}
    randuri = [(u, etichete[rol(u)]) for u in pagina]
    return render(request, 'clinica/asistent/utilizatori.html', {
        'pagina': pagina, 'randuri': randuri, 'q': q, 'param': _fara_pagina(request),
    })


@rol_necesar('asistent')
def asistent_sedinte(request):
    sedinte = Sedinta.objects.select_related('pacient', 'calificare__specialist', 'calificare__grad')
    q = request.GET.get('q', '').strip()
    if q:
        for cuvant in q.split():
            sedinte = sedinte.filter(
                Q(pacient__nume__icontains=cuvant) | Q(pacient__prenume__icontains=cuvant)
                | Q(calificare__specialist__nume__icontains=cuvant)
                | Q(calificare__specialist__prenume__icontains=cuvant)
            )
    status = request.GET.get('status')
    if status in Sedinta.Status.values:
        sedinte = sedinte.filter(status=status)
    return render(request, 'clinica/asistent/sedinte.html', {
        'pagina': _pagina(request, sedinte), 'q': q, 'status_ales': status, 'now': timezone.now(),
        'statusuri': Sedinta.Status.choices, 'param': _fara_pagina(request),
    })
