"""
Modelele aplicației „Clinică online de psihologie”.

Etapa 1: persoane, roluri profesionale, ședințe și notificări.
    Utilizator ──1:1── Pacient
    Utilizator ──1:1── Specialist ──1:N── Calificare ──N:1── GradProfesional ──N:1── Profesie
    Pacient ──1:N── Sedinta ──N:1── Calificare
    Pacient ──1:N── Notificare ──N:1── Sedinta (opțional)

Reguli principale:
    * ordinea gradelor e obligatorie doar la profesiile cu ierarhie legală
    * un specialist are cel mult un grad ACTIV pe profesie + domeniu
    * numărul unui atestat e unic în cadrul organismului emitent
    * o calificare e activată / dezactivată doar de administrator, prin
      Calificare.activeaza() / Calificare.dezactiveaza(), care păstrează cine,
      când și de ce, și mută sau anulează programările viitoare
    * o ședință se programează doar pe o calificare activă, verificată și
      neexpirată la data ședinței

Etapele următoare (tratament, chestionare, alerte, diagnostice) se adaugă
ulterior, prin migrații noi.
"""
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.db import models, transaction
from django.db.models import F, Q
from django.utils import timezone


# ---------------------------------------------------------------------------
# Conturi și persoane
# ---------------------------------------------------------------------------

class Utilizator(AbstractUser):
    """
    Contul de autentificare (username, parolă, permisiuni).

    Conține DOAR date de login. Numele real și datele de contact stau în
    Pacient / Specialist, care se leagă de cont printr-o relație 1:1.
    """

    class Meta:
        verbose_name = 'utilizator'
        verbose_name_plural = 'utilizatori'


class Persoana(models.Model):
    """
    Clasă de bază ABSTRACTĂ: nu creează tabel în baza de date.
    Câmpurile ei sunt copiate în fiecare tabel copil (Pacient, Specialist).
    """
    nume = models.CharField(max_length=100)
    prenume = models.CharField(max_length=100)
    telefon = models.CharField(max_length=20, blank=True)
    data_inregistrare = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True
        ordering = ['nume', 'prenume']

    def __str__(self):
        return f'{self.nume} {self.prenume}'


class Pacient(Persoana):
    """Fișa medicală a pacientului. Poate exista și fără cont (ex: un copil)."""

    class Sex(models.TextChoices):
        FEMININ = 'F', 'Feminin'
        MASCULIN = 'M', 'Masculin'
        ALTUL = 'A', 'Altul / nespecificat'

    # SET_NULL: dacă se șterge contul, fișa medicală rămâne (obligație legală)
    utilizator = models.OneToOneField(
        Utilizator, on_delete=models.SET_NULL, null=True, blank=True, related_name='pacient',
    )
    data_nasterii = models.DateField()
    sex = models.CharField(max_length=1, choices=Sex.choices, blank=True)
    # NU e unic: mai mulți pacienți pot folosi același email
    # (ex: un părinte pentru copiii lui). Autentificarea se face prin Utilizator.
    email = models.EmailField(blank=True)
    contact_urgenta_nume = models.CharField(max_length=150, blank=True)
    contact_urgenta_telefon = models.CharField(max_length=20, blank=True)
    data_consimtamant = models.DateTimeField(
        null=True, blank=True, help_text='Momentul acordului pentru prelucrarea datelor (GDPR).',
    )

    class Meta(Persoana.Meta):
        verbose_name = 'pacient'
        verbose_name_plural = 'pacienți'

    def clean(self):
        if self.data_nasterii and self.data_nasterii > timezone.localdate():
            raise ValidationError({'data_nasterii': 'Data nașterii nu poate fi în viitor.'})


class Specialist(Persoana):
    """Fișa profesională. Profesiile și gradele sunt în Calificare (1:N)."""

    utilizator = models.OneToOneField(
        Utilizator, on_delete=models.SET_NULL, null=True, blank=True, related_name='specialist',
    )
    email = models.EmailField(unique=True)
    descriere = models.TextField(blank=True, help_text='Prezentare scurtă, vizibilă pacienților.')
    accepta_pacienti_noi = models.BooleanField(default=True)

    class Meta(Persoana.Meta):
        verbose_name = 'specialist'
        verbose_name_plural = 'specialiști'


# ---------------------------------------------------------------------------
# Profesii, grade și calificări
#   Profesie (catalog) 1──N GradProfesional (catalog) 1──N Calificare (cine ce deține)
# ---------------------------------------------------------------------------

class Profesie(models.Model):
    """Catalog: psihiatru, psihoterapeut... Drepturile țin de profesie, nu de grad (3NF)."""

    nume = models.CharField(max_length=50, unique=True)
    organism_emitent = models.CharField(
        max_length=100, help_text='Ex: Colegiul Medicilor din România.',
    )
    poate_prescrie = models.BooleanField(default=False)
    poate_diagnostica = models.BooleanField(default=False)
    grade_ierarhice = models.BooleanField(
        default=True,
        help_text='Bifat dacă legislația stabilește o ierarhie a gradelor '
                  '(ex: rezident < specialist < primar). Atunci ordinea gradelor e obligatorie.',
    )

    class Meta:
        verbose_name = 'profesie'
        verbose_name_plural = 'profesii'
        ordering = ['nume']

    def __str__(self):
        return self.nume


class GradProfesional(models.Model):
    """Catalog: combinațiile valide profesie + grad, cu poziția lor în ierarhie."""

    profesie = models.ForeignKey(Profesie, on_delete=models.PROTECT, related_name='grade')
    nume = models.CharField(max_length=50)
    # poziția în ierarhie: rezident (1) < specialist (2) < primar (3).
    # Gol doar la profesiile fără ierarhie legală.
    ordine = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text='Poziția în ierarhie (1 = cel mai mic). Gol doar dacă profesia nu are grade ierarhice.',
    )
    poate_superviza = models.BooleanField(default=False)

    class Meta:
        verbose_name = 'grad profesional'
        verbose_name_plural = 'grade profesionale'
        ordering = ['profesie__nume', 'ordine', 'nume']
        constraints = [
            # același grad nu se definește de două ori în catalog
            models.UniqueConstraint(fields=['profesie', 'nume'], name='grad_nume_unic_pe_profesie'),
            # două grade nu stau pe aceeași treaptă (mai multe NULL-uri nu intră în conflict)
            models.UniqueConstraint(fields=['profesie', 'ordine'], name='grad_ordine_unica_pe_profesie'),
            models.CheckConstraint(
                condition=Q(ordine__isnull=True) | Q(ordine__gte=1), name='grad_ordine_pozitiva',
            ),
        ]

    def __str__(self):
        return f'{self.profesie} {self.nume}'

    def clean(self):
        if self.profesie_id and self.profesie.grade_ierarhice and self.ordine is None:
            raise ValidationError(
                {'ordine': 'Profesia are grade ierarhice, deci ordinea este obligatorie.'}
            )


class Calificare(models.Model):
    """
    Tabel asociativ Specialist ↔ GradProfesional (M:N cu atribute).
    Fiecare rând este un document real (cod de parafă / atestat), emis de
    organismul profesional. Documentele vechi rămân în istoric.

    Stări posibile:
        activă         activa = true,  fără motiv de dezactivare
        în așteptare   activa = false, fără motiv (document nou, neactivat încă)
        dezactivată    activa = false, cu motiv, dată și autor
    """

    class MotivDezactivare(models.TextChoices):
        PROMOVARE = 'promovare', 'Înlocuită de un document superior'
        INCETARE = 'incetare_colaborare', 'Încetarea colaborării cu clinica'
        SUSPENDARE = 'suspendare', 'Suspendarea dreptului de practică'
        RETRAGERE = 'retragere', 'Retragerea dreptului de practică'
        EROARE = 'eroare', 'Document introdus greșit'

    MOTIV_ANULARE_SEDINTE = 'Specialistul nu mai este disponibil.'

    specialist = models.ForeignKey(Specialist, on_delete=models.PROTECT, related_name='calificari')
    grad = models.ForeignKey(GradProfesional, on_delete=models.PROTECT, related_name='calificari')
    domeniu = models.CharField(
        max_length=150, blank=True,
        help_text='Ex: psihoterapie cognitiv-comportamentală. Gol dacă profesia nu are domenii.',
    )
    nr_document = models.CharField(
        max_length=50, db_index=True, help_text='Cod parafă / număr atestat, emis de organismul profesional.',
    )
    data_obtinere = models.DateField()
    data_expirare = models.DateField(null=True, blank=True, help_text='Gol = nu expiră.')
    activa = models.BooleanField(
        default=True,
        help_text='Pentru un document care îl înlocuiește pe unul activ, debifează: '
                  'documentul rămâne „în așteptare” până la acțiunea «Activează».',
    )
    tarif_sedinta = models.DecimalField(max_digits=8, decimal_places=2)

    # verificarea documentului în registrul oficial al organismului emitent
    verificata = models.BooleanField(default=False)
    verificata_de = models.ForeignKey(
        Utilizator, on_delete=models.SET_NULL, null=True, blank=True, related_name='calificari_verificate',
    )
    verificata_la = models.DateTimeField(null=True, blank=True)

    # dezactivarea: cine, când și de ce
    dezactivata_de = models.ForeignKey(
        Utilizator, on_delete=models.SET_NULL, null=True, blank=True, related_name='calificari_dezactivate',
    )
    dezactivata_la = models.DateTimeField(null=True, blank=True)
    motiv_dezactivare = models.CharField(max_length=25, choices=MotivDezactivare.choices, blank=True)

    class Meta:
        verbose_name = 'calificare'
        verbose_name_plural = 'calificări'
        ordering = ['specialist__nume', 'specialist__prenume', 'grad__profesie__nume']
        permissions = [
            ('gestioneaza_calificari', 'Poate verifica, activa și dezactiva calificări'),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(data_expirare__isnull=True) | Q(data_expirare__gt=F('data_obtinere')),
                name='calificare_expirare_dupa_obtinere',
            ),
            models.CheckConstraint(condition=Q(tarif_sedinta__gte=0), name='calificare_tarif_pozitiv'),
            # o calificare verificată trebuie să aibă data verificării
            models.CheckConstraint(
                condition=Q(verificata=False) | Q(verificata_la__isnull=False),
                name='calificare_verificare_datata',
            ),
            # o calificare activă nu are motiv / dată de dezactivare
            models.CheckConstraint(
                condition=Q(activa=False) | (Q(motiv_dezactivare='') & Q(dezactivata_la__isnull=True)),
                name='calificare_activa_fara_dezactivare',
            ),
            # motivul și data dezactivării apar întotdeauna împreună
            models.CheckConstraint(
                condition=(Q(motiv_dezactivare='') & Q(dezactivata_la__isnull=True))
                | (~Q(motiv_dezactivare='') & Q(dezactivata_la__isnull=False)),
                name='calificare_motiv_si_data_dezactivare',
            ),
        ]

    def __str__(self):
        text = f'{self.specialist} – {self.grad}'
        return f'{text} ({self.domeniu})' if self.domeniu else text

    def stare(self):
        if self.activa:
            return 'Activă'
        if not self.motiv_dezactivare:
            return 'În așteptare'
        return f'Dezactivată – {self.get_motiv_dezactivare_display().lower()}'
    stare.short_description = 'stare'

    def _normalizeaza(self):
        self.domeniu = (self.domeniu or '').strip()
        self.nr_document = (self.nr_document or '').strip()

    def _alte_active_in_grup(self):
        """Celelalte calificări active ale aceluiași specialist, în aceeași profesie + domeniu."""
        return (
            Calificare.objects
            .filter(specialist_id=self.specialist_id, activa=True,
                    grad__profesie_id=self.grad.profesie_id, domeniu__iexact=self.domeniu)
            .exclude(pk=self.pk)
        )

    def clean(self):
        # Aceste reguli implică alte rânduri și alte tabele, deci nu se pot scrie
        # cu UNIQUE / CHECK. Le verificăm aici, iar ulterior și prin triggere PostgreSQL.
        self._normalizeaza()
        if not (self.specialist_id and self.grad_id):
            return
        erori = {}
        profesie = self.grad.profesie

        # 1. cel mult un grad ACTIV pe profesie + domeniu
        if self.activa and self._alte_active_in_grup().exists():
            erori[NON_FIELD_ERRORS] = [
                'Specialistul are deja o calificare activă pentru această profesie și acest domeniu. '
                'Adaugă documentul nou cu „activa” debifat, verifică-l, apoi folosește acțiunea «Activează».'
            ]

        # 2. numărul documentului e unic în cadrul organismului emitent
        if self.nr_document:
            duplicat = (
                Calificare.objects
                .filter(nr_document=self.nr_document,
                        grad__profesie__organism_emitent=profesie.organism_emitent)
                .exclude(pk=self.pk)
            )
            if duplicat.exists():
                erori['nr_document'] = [
                    f'Documentul {self.nr_document} emis de {profesie.organism_emitent} este deja înregistrat.'
                ]

        if erori:
            raise ValidationError(erori)

    def save(self, *args, **kwargs):
        self._normalizeaza()
        # dacă se schimbă documentul sau gradul, verificarea veche nu mai e valabilă
        if self.pk:
            vechi = Calificare.objects.filter(pk=self.pk).values('nr_document', 'grad_id').first()
            if vechi and (vechi['nr_document'] != self.nr_document or vechi['grad_id'] != self.grad_id):
                self.verificata = False
                self.verificata_de = None
                self.verificata_la = None
        super().save(*args, **kwargs)

    def este_valabila_la(self, data):
        """True dacă documentul poate fi folosit pentru o ședință la data dată."""
        return self.activa and self.verificata and (self.data_expirare is None or self.data_expirare >= data)

    # ------------------------------------------------------------------
    # Operații de administrare. Fiecare rulează într-o singură tranzacție:
    # ori se aplică toate modificările, ori niciuna.
    # ------------------------------------------------------------------

    _CAMPURI_STARE = ['activa', 'motiv_dezactivare', 'dezactivata_de', 'dezactivata_la']

    def activeaza(self, utilizator):
        """
        Activează un document (nou sau suspendat anterior). Documentele active din
        aceeași profesie + domeniu sunt înlocuite (motiv: promovare), iar programările
        lor viitoare se mută pe acest document. Întoarce numărul de ședințe mutate.
        """
        with transaction.atomic():
            c = (Calificare.objects.select_for_update(of=('self',))
                 .select_related('grad', 'specialist').get(pk=self.pk))
            if c.activa:
                raise ValidationError('Calificarea este deja activă.')
            if c.motiv_dezactivare == self.MotivDezactivare.PROMOVARE:
                raise ValidationError('Un document înlocuit de unul superior nu mai poate fi reactivat.')
            if not c.verificata:
                raise ValidationError('Documentul trebuie verificat în registrul oficial înainte de activare.')

            acum = timezone.now()
            vechi = list(c._alte_active_in_grup().select_for_update(of=('self',)))
            sedinte = list(
                Sedinta.objects
                .filter(calificare__in=vechi, status=Sedinta.Status.PROGRAMATA, data_ora__gte=acum)
                .select_related('pacient')
            )
            if c.data_expirare:
                prea_tarzii = [s for s in sedinte if timezone.localtime(s.data_ora).date() > c.data_expirare]
                if prea_tarzii:
                    raise ValidationError(
                        f'{len(prea_tarzii)} ședințe programate sunt după data expirării noului document '
                        f'({c.data_expirare:%d.%m.%Y}). Mută-le sau anulează-le înainte de activare.'
                    )

            # pacienții sunt anunțați, iar programările își păstrează data și prețul
            Notificare.objects.bulk_create([
                Notificare(
                    pacient=s.pacient, sedinta=s, tip=Notificare.Tip.MUTARE,
                    mesaj=f'Ședința din {timezone.localtime(s.data_ora):%d.%m.%Y, ora %H:%M} rămâne '
                          f'programată. {c.specialist} are acum gradul de {c.grad}.',
                )
                for s in sedinte
            ])
            Sedinta.objects.filter(pk__in=[s.pk for s in sedinte]).update(calificare=c)

            for v in vechi:
                v.activa = False
                v.motiv_dezactivare = self.MotivDezactivare.PROMOVARE
                v.dezactivata_de = utilizator
                v.dezactivata_la = acum
                v.save(update_fields=self._CAMPURI_STARE)

            c.activa = True
            c.motiv_dezactivare = ''
            c.dezactivata_de = None
            c.dezactivata_la = None
            c.save(update_fields=self._CAMPURI_STARE)

        self.refresh_from_db()
        return len(sedinte)

    def dezactiveaza(self, utilizator, motiv):
        """
        Dezactivează documentul din alt motiv decât promovarea. Programările viitoare
        se anulează, iar pacienții primesc o notificare. Întoarce numărul de ședințe anulate.
        """
        if motiv not in self.MotivDezactivare.values or motiv == self.MotivDezactivare.PROMOVARE:
            raise ValidationError('Motiv invalid. Promovarea se face prin activarea documentului nou.')

        with transaction.atomic():
            c = (Calificare.objects.select_for_update(of=('self',))
                 .select_related('specialist').get(pk=self.pk))
            if c.motiv_dezactivare:
                raise ValidationError('Calificarea este deja dezactivată.')

            acum = timezone.now()
            sedinte = list(
                c.sedinte.filter(status=Sedinta.Status.PROGRAMATA, data_ora__gte=acum).select_related('pacient')
            )
            Notificare.objects.bulk_create([
                Notificare(
                    pacient=s.pacient, sedinta=s, tip=Notificare.Tip.ANULARE,
                    mesaj=f'Ședința din {timezone.localtime(s.data_ora):%d.%m.%Y, ora %H:%M} cu '
                          f'{c.specialist} a fost anulată, deoarece specialistul nu mai este disponibil. '
                          f'Vă rugăm să programați o nouă ședință.',
                )
                for s in sedinte
            ])
            Sedinta.objects.filter(pk__in=[s.pk for s in sedinte]).update(
                status=Sedinta.Status.ANULATA, motiv_anulare=self.MOTIV_ANULARE_SEDINTE, anulata_la=acum,
            )

            c.activa = False
            c.motiv_dezactivare = motiv
            c.dezactivata_de = utilizator
            c.dezactivata_la = acum
            c.save(update_fields=self._CAMPURI_STARE)

        self.refresh_from_db()
        return len(sedinte)


# ---------------------------------------------------------------------------
# Ședințe
# ---------------------------------------------------------------------------

class Sedinta(models.Model):
    """
    O ședință online. Indică o CALIFICARE, nu un specialist: astfel se știe
    și cine a ținut-o, și în ce rol (ex: consultație psihiatrică vs. terapie).
    Ședințele nu se șterg la anulare: rămân în istoric cu status „anulată”.
    """

    class Status(models.TextChoices):
        PROGRAMATA = 'programata', 'Programată'
        FINALIZATA = 'finalizata', 'Finalizată'
        ANULATA = 'anulata', 'Anulată'
        NEPREZENTARE = 'neprezentare', 'Neprezentare'

    pacient = models.ForeignKey(Pacient, on_delete=models.PROTECT, related_name='sedinte')
    calificare = models.ForeignKey(Calificare, on_delete=models.PROTECT, related_name='sedinte')
    data_ora = models.DateTimeField()
    durata_minute = models.PositiveSmallIntegerField(default=50)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.PROGRAMATA)
    link_intalnire = models.URLField(blank=True)
    # copie a tarifului din momentul programării (denormalizare intenționată):
    # dacă tariful se schimbă, ședințele vechi păstrează prețul real
    pret = models.DecimalField(
        max_digits=8, decimal_places=2, blank=True,
        help_text='Gol = se preia tariful actual al calificării.',
    )
    note_confidentiale = models.TextField(blank=True, help_text='Vizibile doar specialistului.')
    motiv_anulare = models.CharField(max_length=255, blank=True, help_text='Obligatoriu la anulare.')
    anulata_la = models.DateTimeField(null=True, blank=True)
    creata_la = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'ședință'
        verbose_name_plural = 'ședințe'
        ordering = ['-data_ora']
        constraints = [
            models.CheckConstraint(condition=Q(durata_minute__gt=0), name='sedinta_durata_pozitiva'),
            models.CheckConstraint(condition=Q(pret__gte=0), name='sedinta_pret_pozitiv'),
            # anulată  <=> are motiv și dată de anulare
            models.CheckConstraint(
                condition=(Q(status='anulata') & Q(anulata_la__isnull=False) & ~Q(motiv_anulare=''))
                | (~Q(status='anulata') & Q(anulata_la__isnull=True) & Q(motiv_anulare='')),
                name='sedinta_anulare_completa',
            ),
        ]

    def __str__(self):
        return f'{self.pacient} – {self.calificare} ({timezone.localtime(self.data_ora):%d.%m.%Y %H:%M})'

    def _completeaza_pret(self):
        if self.pret is None and self.calificare_id:
            self.pret = self.calificare.tarif_sedinta

    def _se_programeaza(self):
        """True pentru o ședință nouă sau dacă s-a schimbat calificarea ori data.
        Ședințele existente (istoricul) nu se mai verifică la simple modificări."""
        if self._state.adding:
            return True
        vechi = Sedinta.objects.filter(pk=self.pk).values('calificare_id', 'data_ora').first()
        return vechi is None or vechi['calificare_id'] != self.calificare_id or vechi['data_ora'] != self.data_ora

    def _sincronizeaza_anulare(self):
        """Datele anulării există doar pentru ședințele anulate.
        Rulează înainte de verificarea constrângerilor (în clean) și la salvare."""
        if self.status == self.Status.ANULATA:
            self.motiv_anulare = (self.motiv_anulare or '').strip()
            if self.anulata_la is None and self.motiv_anulare:
                self.anulata_la = timezone.now()
        else:
            # o ședință reprogramată nu mai păstrează datele anulării
            self.anulata_la = None
            self.motiv_anulare = ''

    def clean(self):
        self._completeaza_pret()
        self._sincronizeaza_anulare()
        erori = {}

        if self.status == self.Status.ANULATA and not self.motiv_anulare:
            erori['motiv_anulare'] = ['Precizează motivul anulării.']

        if self.calificare_id and self.data_ora and self._se_programeaza():
            calificare = self.calificare
            data = (timezone.localtime(self.data_ora).date() if timezone.is_aware(self.data_ora)
                    else self.data_ora.date())
            probleme = []
            if not calificare.activa:
                probleme.append('Calificarea selectată nu este activă.')
            if not calificare.verificata:
                probleme.append('Calificarea selectată nu a fost încă verificată în registrul oficial.')
            if calificare.data_expirare and calificare.data_expirare < data:
                probleme.append(
                    f'Documentul expiră pe {calificare.data_expirare:%d.%m.%Y}, înainte de data ședinței.'
                )
            if probleme:
                erori['calificare'] = probleme

        if erori:
            raise ValidationError(erori)

    def save(self, *args, **kwargs):
        self._completeaza_pret()
        self._sincronizeaza_anulare()
        super().save(*args, **kwargs)


# ---------------------------------------------------------------------------
# Notificări
# ---------------------------------------------------------------------------

class Notificare(models.Model):
    """
    Mesaj pentru pacient (ex: ședință anulată sau mutată).
    Pacienții cu cont o văd în aplicație; pentru cei fără cont, administratorul
    îi contactează telefonic și marchează notificarea ca transmisă.
    """

    class Tip(models.TextChoices):
        ANULARE = 'anulare', 'Anulare ședință'
        MUTARE = 'mutare', 'Modificare ședință'
        ALERTA = 'alerta', 'Alertă'
        INFORMARE = 'informare', 'Informare'

    pacient = models.ForeignKey(Pacient, on_delete=models.CASCADE, related_name='notificari')
    sedinta = models.ForeignKey(
        Sedinta, on_delete=models.SET_NULL, null=True, blank=True, related_name='notificari',
    )
    tip = models.CharField(max_length=15, choices=Tip.choices)
    mesaj = models.TextField()
    creata_la = models.DateTimeField(auto_now_add=True)
    citita_la = models.DateTimeField(
        null=True, blank=True, help_text='Când a fost citită în aplicație sau transmisă telefonic.',
    )

    class Meta:
        verbose_name = 'notificare'
        verbose_name_plural = 'notificări'
        ordering = ['-creata_la']

    def __str__(self):
        return f'{self.get_tip_display()} – {self.pacient}'
