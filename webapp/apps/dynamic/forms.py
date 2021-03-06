import six
import ast

from django import forms
from django.forms import ModelForm

from ..taxbrain.helpers import is_safe

from ..constants import START_YEAR
from .models import DynamicElasticitySaveInputs
from .helpers import default_elasticity_parameters


def bool_like(x):
    b = True if x == 'True' or x else False
    return b


ELASTICITY_DEFAULT_PARAMS = default_elasticity_parameters(int(START_YEAR))


class DynamicElasticityInputsModelForm(ModelForm):

    def __init__(self, first_year, use_puf_not_cps, *args, **kwargs):
        self._first_year = int(first_year)
        self._default_params = default_elasticity_parameters(self._first_year)
        # Defaults are set in the Meta, but we need to swap
        # those outs here in the init because the user may
        # have chosen a different start year
        all_defaults = []
        for param in list(self._default_params.values()):
            for field in param.col_fields:
                all_defaults.append((field.id, field.default_value))

        for _id, default in all_defaults:
            self._meta.widgets[_id].attrs['placeholder'] = default

        super(DynamicElasticityInputsModelForm, self).__init__(*args, **kwargs)

    def clean(self):
        """
        " This method should be used to provide custom model validation, and to
        modify attributes on your model if desired. For instance, you could use
        it to automatically provide a value for a field, or to do validation
        that requires access to more than a single field."
        per https://docs.djangoproject.com/en/1.8/ref/models/instances/

        Note that this can be defined both on forms and on the model, but is
        only automatically called on form submissions.
        """
        self.do_taxcalc_validations()

    def do_taxcalc_validations(self):
        """
        Run the validations specified by Taxcalc's param definitions

        Each parameter can be assigned a min and a max, the value of which can
        be statically defined or determined dynamically via a keyword.

        Keywords correlate to submitted value array for a different parameter,
        or to the default value array for the validated field.

        We could define these on individual fields instead, but we would need
        to define all the field data dynamically both here and on the model,
        and it's not yet possible on the model due to issues with how
        migrations are detected.
        """
        exp_keys = {'data_source', 'elastic_gdp', 'first_year', 'micro_run'}
        assert set(self.cleaned_data.keys()) == exp_keys

        param_name, value = 'elastic_gdp', self.cleaned_data['elastic_gdp']
        # make sure the text parses OK
        if isinstance(value, six.string_types) and len(value) > 0:
            if not is_safe(value):
                # Parse Error - we don't recognize what they gave us
                self.add_error(param_name,
                               "Unrecognized value: {}".format(value))
            try:
                # reverse character is not at the beginning
                assert value.find('<') <= 0
            except AssertionError:
                self.add_error(
                    param_name,
                    ("Operator '<' can only be used "
                     "at the beginning")
                )
        else:
            assert isinstance(value, bool) or len(value) == 0

        try:
            evaled = ast.literal_eval(value)
            if evaled < 0.0:
                self.add_error('elastic_gdp', (f'ERROR: {evaled} is less '
                                               f'than the min value 0.0'))
            elif evaled > 1.0:
                self.add_error('elastic_gdp', (f'ERROR: {evaled} is greater '
                                              f'than the max value 1.0'))
        except (SyntaxError, ValueError):
            self.add_error('elastic_gdp', 'ERROR: {evaled} is not an integer')

    class Meta:
        model = DynamicElasticitySaveInputs
        exclude = ['creation_date']
        widgets = {}
        labels = {}
        for param in list(ELASTICITY_DEFAULT_PARAMS.values()):
            for field in param.col_fields:
                attrs = {
                    'class': 'form-control',
                    'placeholder': field.default_value,
                }

                if param.coming_soon:
                    attrs['disabled'] = True
                    attrs['checked'] = False
                    widgets[field.id] = forms.CheckboxInput(
                        attrs=attrs, check_test=bool_like)
                else:
                    widgets[field.id] = forms.TextInput(attrs=attrs)

                labels[field.id] = field.label

            if param.inflatable:
                field = param.cpi_field
                attrs = {
                    'class': 'form-control sr-only',
                    'placeholder': bool(field.default_value),
                }

                if param.coming_soon:
                    attrs['disabled'] = True

                widgets[field.id] = forms.NullBooleanSelect(attrs=attrs)
