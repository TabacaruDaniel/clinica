from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from datetime import timedelta

from .widgets import PAS_MINUTE, DataOraWidget, SelectOraWidget
from .models import Calificare, Pacient, ProgramSpecialist, Sedinta, Specialist, Utilizator


class PacientTelefonicForm(forms.ModelForm):
    """Fișă de pacient creată de specialist, după datele dictate telefonic (fără cont)."""

    acord_verbal = forms.BooleanField(
        label='Pacientul și-a dat acordul verbal pentru prelucrarea datelor personale (GDPR)',
        error_messages={'required': 'Acordul pacientului este necesar.'},
    )

    class Meta:
        model = Pacient
        fields = ['nume', 'prenume', 'data_nasterii', 'telefon', 'email']
        widgets = {'data_nasterii': forms.DateInput(attrs={'type': 'date'})}
        help_texts = {'email': 'Necesar dacă pacientul își va crea ulterior un cont (confirmarea se trimite aici).'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['telefon'].required = True

    def save(self, commit=True):
        pacient = super().save(commit=False)
        pacient.data_consimtamant = timezone.now()
        if commit:
            pacient.save()
        return pacient


class AlegePacientForm(forms.Form):
    """Specialistul poate alege doar pacienți cu care a avut deja ședințe."""

    pacient = forms.ModelChoiceField(queryset=Pacient.objects.none(), label='Pacient')

    def __init__(self, *args, specialist, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['pacient'].queryset = (
            Pacient.objects.filter(sedinte__calificare__specialist=specialist).distinct()
        )


class SedintaTelefonForm(forms.ModelForm):
    """Programarea unei ședințe de către specialist, pe una din calificările lui valabile."""

    class Meta:
        model = Sedinta
        fields = ['calificare', 'data_ora', 'durata_minute', 'link_intalnire']
        labels = {'calificare': 'În calitate de', 'data_ora': 'Data și ora',
                  'durata_minute': 'Durata (minute)', 'link_intalnire': 'Link întâlnire (opțional)'}
        widgets = {'data_ora': DataOraWidget()}

    def __init__(self, *args, specialist=None, pacient=None, **kwargs):
        """specialist: limitează alegerea la calificările lui (None = toate, pentru asistentă).
        pacient: dacă e cunoscut, se verifică și suprapunerea cu ședințele lui."""
        super().__init__(*args, **kwargs)
        self.specialist = specialist
        self.pacient = pacient
        calificari = Calificare.valabile().select_related('specialist', 'grad__profesie')
        if specialist:
            calificari = calificari.filter(specialist=specialist)
        self.fields['calificare'].queryset = calificari
        self.fields['calificare'].empty_label = None

    @staticmethod
    def _verifica_program(specialist, start, sfarsit):
        """Ședința trebuie să încapă integral în programul specialistului din ziua respectivă."""
        start_local = timezone.localtime(start)
        sfarsit_local = timezone.localtime(sfarsit)
        zi = ProgramSpecialist.Zi(start_local.weekday())

        intervale = []
        for p in ProgramSpecialist.objects.filter(specialist=specialist, zi=zi).order_by('ora_inceput'):
            if intervale and p.ora_inceput <= intervale[-1][1]:
                # intervale care se ating (ex: 09–12 și 12–14) se tratează ca unul singur
                intervale[-1][1] = max(intervale[-1][1], p.ora_sfarsit)
            else:
                intervale.append([p.ora_inceput, p.ora_sfarsit])

        incape = (
            sfarsit_local.date() == start_local.date()
            and any(i <= start_local.time() and sfarsit_local.time() <= f for i, f in intervale)
        )
        if incape:
            return
        if intervale:
            program = ', '.join(f'{i:%H:%M}–{f:%H:%M}' for i, f in intervale)
            detaliu = f'Programul din această zi: {program}.'
        else:
            detaliu = 'Nu are program în această zi.'
        raise forms.ValidationError(
            f'Specialistul nu este disponibil {zi.label.lower()} între {start_local:%H:%M} și '
            f'{sfarsit_local:%H:%M}. {detaliu}'
        )

    def clean_data_ora(self):
        data = self.cleaned_data['data_ora']
        if data <= timezone.now():
            raise forms.ValidationError('Data ședinței trebuie să fie în viitor.')
        if timezone.localtime(data).minute % PAS_MINUTE:
            raise forms.ValidationError(f'Ora de început trebuie să fie din {PAS_MINUTE} în {PAS_MINUTE} minute.')
        return data

    def clean(self):
        data = super().clean()
        start, durata, calificare = data.get('data_ora'), data.get('durata_minute'), data.get('calificare')
        if start and durata and calificare:
            sfarsit = start + timedelta(minutes=durata)
            self._verifica_program(calificare.specialist, start, sfarsit)
            filtru = Q(calificare__specialist_id=calificare.specialist_id)
            if self.pacient:
                filtru |= Q(pacient=self.pacient)
            apropiate = Sedinta.objects.filter(
                filtru, status=Sedinta.Status.PROGRAMATA,
                data_ora__lt=sfarsit, data_ora__gt=start - timedelta(hours=12),
            ).select_related('calificare')
            for s in apropiate:
                if s.data_ora + timedelta(minutes=s.durata_minute) > start:
                    cand = f'{timezone.localtime(s.data_ora):%d.%m.%Y %H:%M}'
                    if s.calificare.specialist_id == calificare.specialist_id:
                        cine = 'Ai deja' if self.specialist else 'Specialistul are deja'
                    else:
                        cine = 'Pacientul are deja'
                    raise forms.ValidationError(f'{cine} o ședință în acest interval ({cand}).')
        return data



class SpecialistProfilForm(forms.ModelForm):
    class Meta:
        model = Specialist
        fields = ['descriere', 'accepta_pacienti_noi']
        widgets = {'descriere': forms.Textarea(attrs={'rows': 6, 'style': 'width:100%;max-width:36rem'})}


ProgramFormSet = forms.inlineformset_factory(
    Specialist, ProgramSpecialist, fields=['zi', 'ora_inceput', 'ora_sfarsit'], extra=1, can_delete=True,
    # ore 00–23, minute din 10 în 10 (validat și pe server, în ProgramSpecialist.clean)
    widgets={'ora_inceput': SelectOraWidget(), 'ora_sfarsit': SelectOraWidget()},
)


class InregistrarePacientForm(UserCreationForm):
    """Creează contul (Utilizator) și fișa de pacient în aceeași tranzacție."""

    nume = forms.CharField(max_length=100, label='Nume')
    prenume = forms.CharField(max_length=100, label='Prenume')
    data_nasterii = forms.DateField(
        label='Data nașterii', widget=forms.DateInput(attrs={'type': 'date'}),
    )
    email = forms.EmailField(label='Email')
    telefon = forms.CharField(max_length=20, required=False, label='Telefon')
    consimtamant = forms.BooleanField(
        label='Sunt de acord cu prelucrarea datelor personale (GDPR)',
        error_messages={'required': 'Acordul este necesar pentru a crea un cont.'},
    )

    class Meta(UserCreationForm.Meta):
        model = Utilizator
        fields = ('username',)

    def clean_data_nasterii(self):
        data = self.cleaned_data['data_nasterii']
        if data > timezone.localdate():
            raise forms.ValidationError('Data nașterii nu poate fi în viitor.')
        return data

    @transaction.atomic
    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        user.first_name = self.cleaned_data['prenume']
        user.last_name = self.cleaned_data['nume']
        user.save()
        Pacient.objects.create(
            utilizator=user,
            nume=self.cleaned_data['nume'],
            prenume=self.cleaned_data['prenume'],
            data_nasterii=self.cleaned_data['data_nasterii'],
            email=self.cleaned_data['email'],
            telefon=self.cleaned_data['telefon'],
            data_consimtamant=timezone.now(),
        )
        return user
