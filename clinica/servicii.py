"""Operații care implică mai multe tabele și trebuie să ruleze atomic."""
import logging

from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Pacient, ProgramSpecialist

logger = logging.getLogger(__name__)

# câmpuri completate din fișa contului dacă lipsesc din fișa veche
_CAMPURI_DE_COMPLETAT = [
    'telefon', 'email', 'sex', 'contact_urgenta_nume', 'contact_urgenta_telefon', 'data_consimtamant',
]


def poate_fi_legat(utilizator):
    """Doar conturile de pacient (sau fără fișă) pot fi legate de o fișă de pacient."""
    return not (
        utilizator.is_staff or utilizator.is_superuser
        or hasattr(utilizator, 'specialist') or hasattr(utilizator, 'asistent')
    )


def leaga_cont(fisa, utilizator, de_catre=None):
    """
    Leagă contul de fișa existentă (fără cont). Dacă contul are deja o fișă (cea creată la
    înregistrare), istoricul ei se comasează în fișa veche: ședințe, notificări și orice alt
    tabel care referă pacientul. Fișa contului dispare, iar câmpurile goale ale fișei vechi se
    completează din ea. Întoarce numărul de înregistrări mutate.
    """
    if not poate_fi_legat(utilizator):
        raise ValidationError('Acest cont nu este un cont de pacient.')

    with transaction.atomic():
        fisa = Pacient.objects.select_for_update().get(pk=fisa.pk)
        if fisa.utilizator_id:
            raise ValidationError('Fișa este deja asociată unui cont.')
        alta = Pacient.objects.select_for_update().filter(utilizator=utilizator).first()

        mutate = 0
        if alta:
            # toate relațiile către Pacient, inclusiv cele adăugate ulterior
            for rel in Pacient._meta.related_objects:
                if not rel.one_to_many:
                    raise ValidationError(
                        f'Comasarea nu poate muta relația {rel.related_model.__name__}.{rel.field.name}.'
                    )
                mutate += rel.related_model._default_manager.filter(
                    **{rel.field.name: alta}
                ).update(**{rel.field.name: fisa})

            for camp in _CAMPURI_DE_COMPLETAT:
                if not getattr(fisa, camp) and getattr(alta, camp):
                    setattr(fisa, camp, getattr(alta, camp))
            alta.delete()  # înainte de legare: utilizator este unic pe Pacient

        fisa.utilizator = utilizator
        fisa.save()

    logger.info('Fișa %s legată de contul %s de către %s; %s înregistrări mutate.',
                fisa.pk, utilizator.pk, getattr(de_catre, 'pk', None), mutate)
    return mutate


def comaseaza_program(specialist):
    """
    Unește, pe fiecare zi, intervalele care se suprapun sau se ating (ex: 12–15 și 14–17
    devin 12–17). Un interval inclus în altul dispare. Întoarce câte rânduri au fost eliminate.
    """
    eliminate = 0
    with transaction.atomic():
        randuri = (ProgramSpecialist.objects.select_for_update()
                   .filter(specialist=specialist).order_by('zi', 'ora_inceput', 'ora_sfarsit'))
        curent = None
        extins = False
        for r in list(randuri):
            if curent and curent.zi == r.zi and r.ora_inceput <= curent.ora_sfarsit:
                if r.ora_sfarsit > curent.ora_sfarsit:
                    curent.ora_sfarsit = r.ora_sfarsit
                    extins = True
                r.delete()
                eliminate += 1
            else:
                if extins:
                    curent.save(update_fields=['ora_sfarsit'])
                curent, extins = r, False
        if extins:
            curent.save(update_fields=['ora_sfarsit'])
    return eliminate
