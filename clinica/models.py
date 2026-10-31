from django.contrib.auth.models import AbstractUser
from django.db import models

class Utilizator(AbstractUser):
    """Custom user model. Empty for now; we'll extend it when we add login."""

    class Meta:
        verbose_name = 'utilizator'
        verbose_name_plural = 'utilizatori'

class Specializare(models.Model):
    nume = models.CharField(max_length=100, unique=True)

    class Meta:
        verbose_name = 'specializare'
        verbose_name_plural = 'specializări'
        ordering = ['nume']

    def __str__(self):
        return self.nume

class Medic(models.Model):
    nume = models.CharField(max_length=100)
    prenume = models.CharField(max_length=100)
    email = models.EmailField(unique=True)
    telefon = models.CharField(max_length=20, blank=True)
    # many-to-many: Django creates the junction table automatically
    specializari = models.ManyToManyField(Specializare, related_name='medici', blank=True)

    class Meta:
        verbose_name = 'medic'
        verbose_name_plural = 'medici'
        ordering = ['nume', 'prenume']

    def __str__(self):
        return f'Dr. {self.nume} {self.prenume}'

class Pacient(models.Model):
    nume = models.CharField(max_length=100)
    prenume = models.CharField(max_length=100)
    data_nasterii = models.DateField()
    email = models.EmailField(unique=True)
    telefon = models.CharField(max_length=20, blank=True)

    class Meta:
        verbose_name = 'pacient'
        verbose_name_plural = 'pacienți'
        ordering = ['nume', 'prenume']

    def __str__(self):
        return f'{self.nume} {self.prenume}'

class Programare(models.Model):
    class Status(models.TextChoices):
        PROGRAMATA = 'programata', 'Programată'
        FINALIZATA = 'finalizata', 'Finalizată'
        ANULATA = 'anulata', 'Anulată'

    pacient = models.ForeignKey(Pacient, on_delete=models.PROTECT, related_name='programari')
    medic = models.ForeignKey(Medic, on_delete=models.PROTECT, related_name='programari')
    data_ora = models.DateTimeField()
    durata_minute = models.PositiveSmallIntegerField(default=30)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PROGRAMATA)
    link_intalnire = models.URLField(blank=True)
    observatii = models.TextField(blank=True)

    class Meta:
        verbose_name = 'programare'
        verbose_name_plural = 'programări'
        ordering = ['-data_ora']

    def __str__(self):
        return f'{self.pacient} – {self.medic} ({self.data_ora:%d.%m.%Y %H:%M})'

class Medicament(models.Model):
    denumire = models.CharField(max_length=150)
    forma = models.CharField(max_length=50)          # ex: comprimat, sirop, injecție
    concentratie = models.CharField(max_length=50)   # ex: 500 mg

    class Meta:
        verbose_name = 'medicament'
        verbose_name_plural = 'medicamente'
        ordering = ['denumire']
        constraints = [
            models.UniqueConstraint(
                fields=['denumire', 'forma', 'concentratie'],
                name='medicament_unic',
            ),
        ]

    def __str__(self):
        return f'{self.denumire} {self.concentratie} ({self.forma})'

class PlanTratament(models.Model):
    pacient = models.ForeignKey(Pacient, on_delete=models.PROTECT, related_name='planuri')
    medic = models.ForeignKey(Medic, on_delete=models.PROTECT, related_name='planuri')
    # optional one-to-one: a plan may come from at most one appointment
    programare = models.OneToOneField(
        Programare, on_delete=models.SET_NULL, null=True, blank=True, related_name='plan'
    )
    diagnostic = models.CharField(max_length=255)
    descriere = models.TextField(blank=True)
    data_inceput = models.DateField()
    data_sfarsit = models.DateField(null=True, blank=True)
    # many-to-many WITH extra data, through an explicit junction model
    medicamente = models.ManyToManyField(Medicament, through='PozitieReteta', related_name='planuri')

    class Meta:
        verbose_name = 'plan de tratament'
        verbose_name_plural = 'planuri de tratament'
        ordering = ['-data_inceput']

    def __str__(self):
        return f'{self.diagnostic} – {self.pacient}'

class PozitieReteta(models.Model):
    plan = models.ForeignKey(PlanTratament, on_delete=models.CASCADE, related_name='pozitii')
    medicament = models.ForeignKey(Medicament, on_delete=models.PROTECT)
    doza = models.CharField(max_length=100)        # ex: 1 comprimat
    frecventa = models.CharField(max_length=100)   # ex: la 8 ore
    durata_zile = models.PositiveSmallIntegerField()
    instructiuni = models.TextField(blank=True)

    class Meta:
        verbose_name = 'poziție rețetă'
        verbose_name_plural = 'poziții rețetă'

    def __str__(self):
        return f'{self.medicament} – {self.doza}, {self.frecventa}'
