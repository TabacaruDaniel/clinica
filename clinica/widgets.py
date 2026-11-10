"""
Selectoare de oră și dată+oră: ore 00–23 și minute din 10 în 10, fără AM/PM.
Valoarea trimisă către câmpul Django este un text obișnuit („14:30” / „2026-11-20 14:30”),
deci TimeField / DateTimeField funcționează neschimbate.
"""
import datetime

from django import forms
from django.utils import timezone

PAS_MINUTE = 10


def _ore():
    return [('', 'oră')] + [(f'{h:02d}', f'{h:02d}') for h in range(24)]


def _minute():
    return [('', 'min')] + [(f'{m:02d}', f'{m:02d}') for m in range(0, 60, PAS_MINUTE)]


def _alege(widgets, data, files, name):
    return [w.value_from_datadict(data, files, f'{name}_{i}') for i, w in enumerate(widgets)]


class SelectOraWidget(forms.MultiWidget):
    template_name = 'clinica/widgets/ora.html'

    def __init__(self, attrs=None):
        super().__init__([
            forms.Select(choices=_ore(), attrs={'aria-label': 'Ora'}),
            forms.Select(choices=_minute(), attrs={'aria-label': 'Minutele'}),
        ], attrs)

    def decompress(self, value):
        if isinstance(value, str):
            try:
                value = datetime.time.fromisoformat(value)
            except ValueError:
                return [None, None]
        if value:
            return [f'{value.hour:02d}', f'{value.minute:02d}']
        return [None, None]

    def value_from_datadict(self, data, files, name):
        ora, minute = _alege(self.widgets, data, files, name)
        if not ora or not minute:
            return None
        return f'{ora}:{minute}'


class DataOraWidget(forms.MultiWidget):
    template_name = 'clinica/widgets/data_ora.html'

    def __init__(self, attrs=None):
        super().__init__([
            forms.DateInput(attrs={'type': 'date', 'aria-label': 'Data'}, format='%Y-%m-%d'),
            forms.Select(choices=_ore(), attrs={'aria-label': 'Ora'}),
            forms.Select(choices=_minute(), attrs={'aria-label': 'Minutele'}),
        ], attrs)

    def decompress(self, value):
        if isinstance(value, str):
            try:
                value = datetime.datetime.fromisoformat(value)
            except ValueError:
                return [None, None, None]
        if value:
            if timezone.is_aware(value):
                value = timezone.localtime(value)
            return [value.date(), f'{value.hour:02d}', f'{value.minute:02d}']
        return [None, None, None]

    def value_from_datadict(self, data, files, name):
        data_, ora, minute = _alege(self.widgets, data, files, name)
        if not data_ or not ora or not minute:
            return None
        return f'{data_} {ora}:{minute}'
