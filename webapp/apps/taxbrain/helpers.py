from collections import namedtuple
import numbers
import os
import pandas as pd
import numpy as np
import pyparsing as pp
import sys
import time
import six
import re

#Mock some module for imports because we can't fit them on Heroku slugs
from mock import Mock
import sys

from ..constants import (START_YEAR,
                         TAXCALC_VERS_RESULTS_BACKWARDS_INCOMPATIBLE)

import taxcalc
from taxcalc import Policy
PYTHON_MAJOR_VERSION = sys.version_info.major
INT_TO_NTH_MAP = ['first', 'second', 'third', 'fourth', 'fifth', 'sixth',
                  'seventh', 'eighth', 'nineth', 'tenth']

SPECIAL_INFLATABLE_PARAMS = {'_II_credit', '_II_credit_ps'}
SPECIAL_NON_INFLATABLE_PARAMS = {'_ACTC_ChildNum', '_EITC_MinEligAge',
                                 '_EITC_MaxEligAge'}

BOOL_PARAMS = ['DependentCredit_before_CTC']

# Grammar for Field inputs
TRUE = pp.CaselessKeyword('true')
FALSE = pp.CaselessKeyword('false')
WILDCARD = pp.Word('*')
INT_LIT = pp.Word(pp.nums)
NEG_DASH = pp.Word('-', exact=1)
FLOAT_LIT = pp.Word(pp.nums + '.')
DEC_POINT = pp.Word('.', exact=1)
FLOAT_LIT_FULL = pp.Word(pp.nums + '.' + pp.nums)
COMMON = pp.Word(",", exact=1)
REVERSE = pp.Word("<") + COMMON

VALUE = WILDCARD | NEG_DASH | FLOAT_LIT_FULL | FLOAT_LIT | INT_LIT
MORE_VALUES = COMMON + VALUE

BOOL = WILDCARD | TRUE | FALSE
MORE_BOOLS = COMMON + BOOL
INPUT = pp.Optional(REVERSE) + BOOL + pp.ZeroOrMore(MORE_BOOLS) | pp.Optional(REVERSE) + VALUE + pp.ZeroOrMore(MORE_VALUES)

TRUE_REGEX = re.compile('(?i)true')
FALSE_REGEX = re.compile('(?i)false')

def is_wildcard(x):
    if isinstance(x, six.string_types):
        return x in ('*', u'*') or x.strip() in ('*', u'*')
    else:
        return False


def is_reverse(x):
    if isinstance(x, six.string_types):
        return x in ('<', u'<') or x.strip() in ('<', u'<')
    else:
        return False


def check_wildcards(x):
    if isinstance(x, list):
        return any([check_wildcards(i) for i in x])
    else:
        return is_wildcard(x)


def make_bool(x):
    """
    Find exact match for case insensitive true or false
    Returns True for True or 1
    Returns False for False or 0
    If x is wildcard then simply return x
    """
    if is_wildcard(x):
        return x
    elif x in (True, '1', '1.0', 1, 1.0):
        return True
    elif x in (False, '0', '0.0', 0, 0.0):
        return False
    elif TRUE_REGEX.match(x, endpos=4):
        return True
    elif FALSE_REGEX.match(x, endpos=5):
        return False
    else:
        # this should be caught much earlier either in model validation or in
        # form validation
        raise ValueError(
            "Expected case insensitive 'true' or 'false' but got {}".format(x)
        )

def convert_val(x):
    if is_wildcard(x):
        return x
    if is_reverse(x):
        return x
    try:
        return float(x)
    except ValueError:
        return make_bool(x)


def int_to_nth(x):
    if x < 1:
        return None
    elif x < 11:
        return INT_TO_NTH_MAP[x - 1]
    else:
        # we need to use an inflection library to support any value
        raise NotImplementedError("Not implemented for x > 10")

def is_number(x):
    return isinstance(x, numbers.Number)

def is_string(x):
    if PYTHON_MAJOR_VERSION == 2:
        return isinstance(x, basestring)
    elif PYTHON_MAJOR_VERSION == 3:
        return isinstance(x, str)

def string_to_float(x):
    return float(x.replace(',', ''))

def string_to_float_array(s):
    if len(s) > 0:
        return [float(x) for x in s.split(',')]
    else:
        return []

def same_version(v1, v2):
    idx = v1.rfind('.')
    return v1[:idx] == v2[:idx]

def arrange_totals_by_row(tots, keys):
    out = {}
    for key in keys:
        order_map = {}
        for name in tots:
            if name.startswith(key):
                year_num = int(name[name.rfind('_')+1:])
                order_map[year_num] = tots[name]
        vals = [order_map[i] for i in range(len(order_map))]
        out[key] = vals
    return out

def round_gt_one_to_nearest_int(values):
    ''' round every value to the nearest integer '''
    def round_gt_one(x):
        if x >= 1.0:
            return round(x)
        else:
            return x
    try:
        rounded = map(round_gt_one, values)
    except TypeError:
        rounded = [map(round_gt_one, val) for val in values]

    return rounded


def default_taxcalc_data(cls, start_year, metadata=False):
    ''' Call the default data function on the given class for the given
        start year with meatadata flag
    '''
    dd = cls.default_data(metadata=metadata, start_year=start_year)
    if metadata:
        for k in dd:
            dd[k]['value'] = round_gt_one_to_nearest_int(dd[k]['value'])
    else:
        for k in dd:
            dd[k] = round_gt_one_to_nearest_int(dd[k])
    return dd

#
# Prepare user params to send to DropQ/Taxcalc
#

tcversion_info = taxcalc._version.get_versions()
taxcalc_version = tcversion_info['version']

TAXCALC_COMING_SOON_FIELDS = []

TAXCALC_COMING_SOON_INDEXED_BY_MARS = []

TAXCALC_HIDDEN_FIELDS = [
    '_ACTC_Income_thd',
    '_AMT_Child_em', '_AMT_em_pe', '_AMT_thd_MarriedS',
    '_CDCC_ps', '_CDCC_crt',
    '_DCC_c',
    '_EITC_InvestIncome_c', '_EITC_ps_MarriedJ',
    '_ETC_pe_Single', '_ETC_pe_Married',
    '_KT_c_Age',
    '_LLC_Expense_c', '_FEI_ec_c'
]

INPUTS_META = (u'has_errors', u'csrfmiddlewaretoken', u'start_year',
          u'full_calc', u'quick_calc', 'first_year', '_state',
          'creation_date', 'id', 'job_ids', 'jobs_not_ready',
          'json_text_id', 'tax_result', 'reform_style',
          '_micro_sim_cache', 'micro_sim_id', 'raw_fields',)

#
# Display TaxCalc result data
#
TAXCALC_RESULTS_START_YEAR = START_YEAR
TAXCALC_RESULTS_MTABLE_COL_LABELS = taxcalc.DIST_TABLE_LABELS[:-2]
TAXCALC_RESULTS_DFTABLE_COL_LABELS = taxcalc.DIFF_TABLE_LABELS[:-2]
TAXCALC_RESULTS_MTABLE_COL_FORMATS = [
    #   divisor,   unit,   decimals
    [      1000,      None, 0], # 'Returns',
    [1000000000, 'Dollars', 1],  # 'AGI',
    [      1000,      None, 0],  # 'Standard Deduction Filers',
    [1000000000, 'Dollars', 1],  # 'Standard Deduction',
    [      1000,      None, 0],  # 'Itemizers',
    [1000000000, 'Dollars', 1],  # 'Itemized Deduction',
    [1000000000, 'Dollars', 1],  # 'Personal Exemption',
    [1000000000, 'Dollars', 1],  # 'Taxable Income',
    [1000000000, 'Dollars', 1],  # 'Regular Tax',
    [1000000000, 'Dollars', 1],  # 'AMTI',
    [      1000,      None, 0],  # 'AMT Filers',
    [1000000000, 'Dollars', 1],  # 'AMT',
    [1000000000, 'Dollars', 1],  # 'Tax before Credits',
    [1000000000, 'Dollars', 1],  # 'Non-refundable Credits',
    [1000000000, 'Dollars', 1],  # 'Tax before Refundable Credits',
    [1000000000, 'Dollars', 1],  # 'Refundable Credits',
    [1000000000, 'Dollars', 1],  # 'Individual Income Liabilities',
    [1000000000, 'Dollars', 1],  # 'Payroll Tax Liablities',
    [1000000000, 'Dollars', 1],  # 'Combined Payroll and individual Income Tax Liablities'

]
TAXCALC_RESULTS_DFTABLE_COL_FORMATS = [
    [      1000,      None, 0],    # "Count", --> All Tax Units
    [      1000,      None, 0],    # "Tax Units with Tax Cut",
    [         1,        '%',1],    # "Percent Tax Decrease" --> "Percent with Tax Cut"
    [      1000,      None, 0],    # "Tax Units with Tax Cut",
    [         1,       '%', 1],    # "Percent Tax Increase" --> "Percent with Tax Increase"
    [         1, 'Dollars', 0],    # "Average Tax Change"
    [1000000000, 'Dollars', 1],    # "Total Tax Difference",
    [         1,   '%', 1],       # "Share of Overall Change"
]
TAXCALC_RESULTS_BIN_ROW_KEYS = taxcalc.WEBBIN_ROW_NAMES
TAXCALC_RESULTS_BIN_ROW_KEY_LABELS = {
    '<$10K':'Less than 10',
    '$10-20K':'10-20',
    '$20-30K':'20-30',
    '$30-40K':'30-40',
    '$40-50K':'40-50',
    '$50-75K':'50-75',
    '$75-100K':'75-100',
    '$100-200K':'100-200',
    '$200-500K':'200-500',
    '$500-1000K':'500-1000',
    '>$1000K':'1000+',
    'all':'All'
}
TAXCALC_RESULTS_DEC_ROW_KEYS = taxcalc.DECILE_ROW_NAMES[:-3]
# -DEC_ROW_NAMES = ['perc0-10', 'perc10-20', 'perc20-30', 'perc30-40',
# -                 'perc40-50', 'perc50-60', 'perc60-70', 'perc70-80',
# -                 'perc80-90', 'perc90-100', 'all']
# -
# -BIN_ROW_NAMES = ['less_than_10', 'ten_twenty', 'twenty_thirty', 'thirty_forty',
# -                 'forty_fifty', 'fifty_seventyfive', 'seventyfive_hundred',
# -                 'hundred_twohundred', 'twohundred_fivehundred',
# -                 'fivehundred_thousand', 'thousand_up', 'all']
# +DEC_ROW_NAMES = ['0-10', '10-20', '20-30', '30-40',
# +                 '40-50', '50-60', '60-70', '70-80',
# +                 '80-90', '90-100', 'all']
# +
# +BIN_ROW_NAMES = ['<$10K', '$10-20K', '$20-30K', '$30-40K',
# +                 '$40-50K', '$50-75K', '$75-100K',
# +                 '$100-200K', '$200-500K',
# +                 '$500-1000K', '>$1000K', 'all']

PRE_TC_0130_RES_MAP = {
    'all': 'all',
    'fifty_seventyfive': '$50-75K',
    'fivehundred_thousand': '$500-1000K',
    'forty_fifty': '$40-50K',
    'hundred_twohundred': '$100-200K',
    'less_than_10': '<$10K',
    'perc0-10': '0-10',
    'perc10-20': '10-20',
    'perc20-30': '20-30',
    'perc30-40': '30-40',
    'perc40-50': '40-50',
    'perc50-60': '50-60',
    'perc60-70': '60-70',
    'perc70-80': '70-80',
    'perc80-90': '80-90',
    'perc90-100': '90-100',
    'seventyfive_hundred': '$75-100K',
    'ten_twenty': '$10-20K',
    'thirty_forty': '$30-40K',
    'thousand_up': '>$1000K',
    'twenty_thirty': '$20-30K',
    'twohundred_fivehundred': '$200-500K',
    'mY_dec': 'dist2_xdec',
    'mX_dec': 'dist1_xdec',
    'df_dec': 'diff_itax_xdec',
    'pdf_dec': 'diff_ptax_xdec',
    'cdf_dec': 'diff_comb_xdec',
    'mY_bin': 'dist2_xbin',
    'mX_bin': 'dist1_xbin',
    'df_bin': 'diff_itax_xbin',
    'pdf_bin': 'diff_ptax_xbin',
    'cdf_bin': 'diff_comb_xbin',
    'fiscal_tot_diffs': 'aggr_d',
    'fiscal_tot_base': 'aggr_1',
    'fiscal_tot_ref': 'aggr_2'
}

TAXCALC_RESULTS_DEC_ROW_KEY_LABELS = {
    '0-10':'0-10%',
    '10-20':'10-20%',
    '20-30':'20-30%',
    '30-40':'30-40%',
    '40-50':'40-50%',
    '50-60':'50-60%',
    '60-70':'60-70%',
    '70-80':'70-80%',
    '80-90':'80-90%',
    '90-100':'90-100%',
    'all':'All'
}
TAXCALC_RESULTS_TABLE_LABELS = {
    'diff_comb_xbin': 'Combined Payroll and Individual Income Tax: Difference between Base and User plans by expanded income bin',
    'diff_comb_xdec': 'Combined Payroll and Individual Income Tax: Difference between Base and User plans by expanded income decile',
    'diff_itax_xbin': 'Individual Income Tax: Difference between Base and User plans by expanded income bin',
    'diff_itax_xdec': 'Individual Income Tax: Difference between Base and User plans by expanded income decile',
    'diff_ptax_xbin': 'Payroll Tax: Difference between Base and User plans by expanded income bin',
    'diff_ptax_xdec': 'Payroll Tax: Difference between Base and User plans by expanded income decile',
    'dist1_xbin': 'Base plan tax vars, weighted total by expanded income bin',
    'dist1_xdec': 'Base plan tax vars, weighted total by expanded income decile',
    'dist2_xbin': 'User plan tax vars, weighted total by expanded income bin',
    'dist2_xdec': 'User plan tax vars, weighted total by expanded income decile',
    'aggr_1': 'Total Liabilities Baseline by Calendar Year',
    'aggr_d': 'Total Liabilities Change by Calendar Year',
    'aggr_2': 'Total Liabilities Reform by Calendar Year'
}

AGG_ROW_NAMES = taxcalc.tbi_utils.AGGR_ROW_NAMES
TAXCALC_RESULTS_TOTAL_ROW_KEY_LABELS = {
    'ind_tax':'Individual Income Tax Liability Change',
    'payroll_tax':'Payroll Tax Liability Change',
    'combined_tax':'Combined Payroll and Individual Income Tax Liability Change',
}

REORDER_LT_TC_0130_DIFF_LIST = [1, 3, 0, 5, 6, 4, 2, 7]
DIFF_TABLE_IDs = ['diff_itax_xdec', 'diff_ptax_xdec', 'diff_comb_xdec',
                  'diff_itax_xbin', 'diff_ptax_xbin', 'diff_comb_xbin']


def expand_1D(x, num_years):
    """
    Expand the given data to account for the given number of budget years.
    Expanded entries are None by default
    """

    if len(x) >= num_years:
        return list(x)
    else:
        ans = [None] * num_years
        ans[:len(x)] = x
        return ans


def expand_2D(x, num_years):
    """
    Expand the given data to account for the given number of budget years.
    For 2D arrays, we expand out the number of rows until we have num_years
    number of rows. Added rows have all 'None' entries
    """

    if len(x) >= num_years:
        return list(x)
    else:
        ans = []
        for i in range(0, num_years):
            ans.append([None] * len(x[0]))
        for i, arr in enumerate(x):
            ans[i] = arr
        return ans


def expand_list(x, num_years):
    """
    Dispatch to either expand_1D or expand2D depending on the dimension of x

    Parameters:
    -----------
    x : value to expand

    num_years: int
    Number of budget years to expand

    Returns:
    --------
    expanded list
    """
    if isinstance(x[0], list):
        return expand_2D(x, num_years)
    else:
        return expand_1D(x, num_years)


def propagate_user_list(x, name, defaults, cpi, first_budget_year,
                        multi_param_idx=-1):
    """
    Dispatch to either expand_1D or expand2D depending on the dimension of x

    Parameters:
    -----------
    x : list from user to propagate forward in time. The first value is for
        year 'first_budget_year'. The value at index i is the value for
        budget year first_budget_year + i.

    defaults: list of default values; our result must be at least this long

    name: the parameter name for looking up the indexing rate

    cpi: Bool

    first_budget_year: int

    multi_param_idx: int, optional. If this parameter is multi-valued, this
        is the index for which the values for 'x' apply. So, for exampe, if
        multi_param_idx=0, the values for x are typically for the 'single'
        filer status. -1 indidcates that this is not a multi-valued
        parameter

    Returns:
    --------
    list of length 'num_years'. if 'cpi'==True, the values will be inflated
    based on the last value the user specified

    """
    # x must have a real first value
    assert len(x) > 0
    assert x[0] not in ("", None)

    num_years = max(len(defaults), len(x))

    is_rate = any([ i < 1.0 for i in x])

    current_policy = Policy(start_year=2013)
    current_policy.set_year(first_budget_year)
    # irates are rates for 2015, 2016, and 2017
    if cpi:
        irates = current_policy._indexing_rates_for_update(param_name=name,
                                              calyear=first_budget_year,
                                              num_years_to_expand=num_years)
    else:
        irates = [0.0] * num_years

    last_val = x[-1]
    ans = [None] * num_years
    for i in range(num_years):
        if i < len(x):
            if is_wildcard(x[i]):
                if multi_param_idx > -1:
                    ans[i] = defaults[i][multi_param_idx]
                else:
                    ans[i] = defaults[i]

            else:
                ans[i] = x[i]

        if ans[i] is not None:
            continue
        else:
            newval = ans[i-1] * (1.0 + irates[i-1])
            ans[i] = newval if is_rate else int(newval)

    return ans


def convert_to_floats(tsi):
    """
    A helper function that tax all of the fields of a TaxSaveInputs model
    and converts them to floats, or list of floats
    """
    def numberfy_one(x):
        if isinstance(x, float):
            return x
        else:
            return float(x)

    def numberfy(x):
        if isinstance(x, list):
            return [numberfy_one(i) for i in x]
        else:
            return numberfy_one(x)

    attrs = vars(tsi)
    return { k:numberfy(v) for k,v in attrs.items() if v}


def leave_name_in(key, val, dd):
    """
    Under certain conditions, we will remove 'key' and its value
    from the dictionary we pass to the dropq package. This function
    will test those conditions and return a Bool.

    Parameters:
    -----------
    key: a field name to potentially pass to the dropq package

    dd: the default dictionary of data in taxcalc Parameters

    Returns:
    --------
    Bool: True if we allow this field to get passed on. False
          if it should be removed.
    """

    if key in dd:
        return True
    elif key in ["elastic_gdp"]:
        return True
    else:
        print "Don't have this pair: ", key, val
        underscore_name_in_defaults = "_" + key in dd
        is_cpi_name = key.endswith("_cpi")
        is_array_name = (key.endswith("_0") or key.endswith("_1") or
                         key.endswith("_2") or key.endswith("_3"))
        if (underscore_name_in_defaults or is_cpi_name or is_array_name):
            return True
        else:
            return False


def package_up_vars(user_values, first_budget_year):
    dd = default_taxcalc_data(taxcalc.policy.Policy, start_year=first_budget_year)
    dd_meta = default_taxcalc_data(taxcalc.policy.Policy,
                                   start_year=first_budget_year, metadata=True)
    growth_dd = default_taxcalc_data(taxcalc.growdiff.Growdiff,
                                     start_year=first_budget_year)

    behavior_dd = default_taxcalc_data(taxcalc.Behavior, start_year=first_budget_year)
    dd.update(growth_dd)
    dd.update(behavior_dd)
    dd.update({"elastic_gdp":[0.54]})
    dd_meta.update({"elastic_gdp":{'values':[0.54], 'cpi_inflated':False}})
    dd_meta.update(default_taxcalc_data(taxcalc.Behavior,
                                        start_year=first_budget_year,
                                        metadata=True))
    dd_meta.update(default_taxcalc_data(taxcalc.policy.Policy,
                                        start_year=first_budget_year,
                                        metadata=True))
    dd_meta.update(default_taxcalc_data(taxcalc.growdiff.Growdiff,
                                        start_year=first_budget_year,
                                        metadata=True))
    for k, v in user_values.items():
        if not leave_name_in(k, v, dd):
            print "Removing ", k, v
            del user_values[k]

    def discover_cpi_flag(param):
        ''' Helper function to discover the CPI setting for this parameter'''

        cpi_flag_from_user = user_values.get(param + "_cpi", None)
        if cpi_flag_from_user is None:
            cpi_flag_from_user = user_values.get("_" + param + "_cpi", None)

        if cpi_flag_from_user is None:
            attrs = dd_meta[param]
            cpi_flag = attrs.get('cpi_inflated', False)
        else:
            cpi_flag = cpi_flag_from_user
        return cpi_flag



    name_stems = {}
    ans = {}
    #Find the 'broken out' array values, these have special treatment
    for k, v in user_values.items():
        if (k.endswith("_0") or k.endswith("_1") or k.endswith("_2")
                or k.endswith("_3")):
            vals = name_stems.setdefault(k[:-2], [])
            vals.append(k)

    #For each array value, expand as necessary based on default data
    #then add user values. It is acceptable to leave 'blanks' as None.
    #This is handled on the taxcalc side
    for k, vals in name_stems.items():
        if k in dd:
            default_data = dd[k]
            param = k
        else:
            #add a leading underscore
            default_data = dd["_" + k]
            param = "_" + k

        # Discover the CPI setting for this parameter
        cpi_flag = discover_cpi_flag(param)

        # get max number of years to advance
        _max = 0
        for name in vals:
            num_years = len(user_values[name])
            if num_years > _max:
                _max = num_years
        expnded_defaults = expand_list(default_data, _max)
        #Now copy necessary data to expanded array
        for name in sorted(vals):
            idx = int(name[-1]) # either 0, 1, 2, 3
            user_arr = user_values[name]
            # Handle wildcards from user
            has_wildcards = check_wildcards(user_arr)
            if len(user_arr) < expnded_defaults or has_wildcards:
                user_arr = propagate_user_list(user_arr, name=param,
                                               defaults=expnded_defaults,
                                               cpi=cpi_flag,
                                               first_budget_year=first_budget_year,
                                               multi_param_idx=idx)
            for new_arr, user_val in zip(expnded_defaults, user_arr):
                new_arr[idx] = int(user_val) if user_val > 1.0 else user_val
            del user_values[name]
        ans[param] = expnded_defaults

    #Process remaining values set by user
    for k, vals in user_values.items():
        if k in dd:
            param = k
        elif k.endswith("_cpi"):
            if k[:-4] in dd:
                ans[k] = vals
            else:
                ans['_' + k] = vals
            continue
        else:
            #add a leading underscore
            param = "_" + k

        # Handle wildcards from user
        has_wildcards = check_wildcards(vals)

        default_data = dd[param]
        _max = max(len(default_data), len(vals))

        if has_wildcards:
            default_data = expand_list(default_data, _max)

        # Discover the CPI setting for this parameter
        cpi_flag = discover_cpi_flag(param)

        if len(vals) < len(default_data) or has_wildcards:
            vals = propagate_user_list(vals, name=param,
                                    defaults=default_data,
                                    cpi=cpi_flag,
                                    first_budget_year=first_budget_year)

        ans[param] = vals

    return ans


#
# Gather data to assist in displaying TaxCalc param form
#

class TaxCalcField(object):
    """
    An atomic unit of data for a TaxCalcParam, which can be stored as a field
    Used for both CSV float fields (value column data) and boolean fields (cpi)
    """
    def __init__(self, id, label, values, param, first_budget_year):
        self.id = id
        self.label = label
        self.values = values
        self.param = param

        self.values_by_year = {}
        for i, value in enumerate(values):
            year = param.start_year + i
            self.values_by_year[year] = value

        self.default_value = self.values_by_year[first_budget_year]


class TaxCalcParam(object):
    """
    A collection of TaxCalcFields that represents all configurable details
    for one of TaxCalc's Parameters
    """
    FORM_HIDDEN_PARAMS = ["widow", "separate", "dependent"]

    def __init__(self, param_id, attributes, first_budget_year,
                 use_puf_not_cps=True):
        self.__load_from_json(param_id, attributes, first_budget_year,
                              use_puf_not_cps)

    def __load_from_json(self, param_id, attributes, first_budget_year,
                         use_puf_not_cps):
        values_by_year = attributes['value']
        col_labels = attributes.get('col_label', '')

        self.tc_id = param_id
        self.nice_id = param_id[1:] if param_id[0] == '_' else param_id
        self.name = attributes['long_name']
        self.info = " ".join([
            attributes['description'],
            attributes.get('irs_ref') or "",  # sometimes this is blank
            attributes.get('notes') or ""     # sometimes this is blank
            ]).strip()

        # check that only parameters that are compatible with the current
        # data set are used
        if "compatible_data" in attributes:
            self.gray_out = not (
                (attributes["compatible_data"]["cps"] and not use_puf_not_cps) or
                (attributes["compatible_data"]["puf"] and use_puf_not_cps)
            )
        else:
            # if compatible_data is not specified do not gray out
            self.gray_out = False

        # Pretend the start year is 2015 (instead of 2013),
        # until values for that year are provided by taxcalc
        #self.start_year = int(attributes['start_year'])
        self.start_year = first_budget_year

        self.coming_soon = (self.tc_id in TAXCALC_COMING_SOON_FIELDS)
        self.hidden = (self.tc_id in TAXCALC_HIDDEN_FIELDS)

        # normalize single-year default lists [] to [[]]
        if not isinstance(values_by_year[0], list):
            values_by_year = [values_by_year]

        # organize defaults by column [[A1,B1],[A2,B2]] to [[A1,A2],[B1,B2]]
        values_by_col = [list(x) for x in zip(*values_by_year)]

        # Tax-Calculator converts boolean values to 1/0 via
        # np.array(bool_val, np.int8)
        # here we convert that value back to a boolean type and serialize it
        if self.nice_id in BOOL_PARAMS:
            assert (isinstance(values_by_col, list) and
                    isinstance(values_by_col[0], list))
            for i in range(len(values_by_col[0])):
                values_by_col[0][i] = str(make_bool(values_by_col[0][i]))
        #
        # normalize and format column labels
        #
        if self.tc_id in TAXCALC_COMING_SOON_INDEXED_BY_MARS:
            col_labels = ["Single", "Married filing Jointly",
                              "Married filing Separately", "Head of Household"]
            values_by_col = ['0','0','0','0']

        elif isinstance(col_labels, list):
            if col_labels == ["0kids", "1kid", "2kids", "3+kids"]:
                col_labels = ["0 Kids", "1 Kid", "2 Kids", "3+ Kids"]

            elif set(col_labels) & set(self.FORM_HIDDEN_PARAMS):
                col_labels = ["Single", "Married filing Jointly",
                              "Married filing Separately", "Head of Household"]

        else:
            if col_labels == "NA" or col_labels == "":
                col_labels = [""]
            elif col_labels == "0kids 1kid  2kids 3+kids":
                col_labels =  ["0 Kids", "1 Kid", "2 Kids", "3+ Kids"]


        # create col params
        self.col_fields = []

        if len(col_labels) == 1:
            self.col_fields.append(TaxCalcField(
                self.nice_id,
                col_labels[0],
                values_by_col[0],
                self,
                first_budget_year
            ))
        else:
            for col, label in enumerate(col_labels):
                self.col_fields.append(TaxCalcField(
                    self.nice_id + "_{0}".format(col),
                    label,
                    values_by_col[col],
                    self,
                    first_budget_year
                ))

        # get attribute indicating whether parameter is cpi inflatable.
        self.inflatable = attributes.get("cpi_inflatable", False)

        if self.inflatable:
            cpi_flag = attributes['cpi_inflated']
            self.cpi_field = TaxCalcField(self.nice_id + "_cpi", "CPI",
                                          [cpi_flag], self, first_budget_year)

        # Get validation details
        validations_json =  attributes.get('validations')
        if validations_json:
            self.max = validations_json.get('max')
            self.min = validations_json.get('min')
        else:
            self.max = None
            self.min = None

        # Coax string-formatted numerics to floats and field IDs to nice IDs
        if self.max:
            if is_string(self.max):
                try:
                    self.max = string_to_float(self.max)
                except ValueError:
                    if self.max[0] == '_':
                        self.max = self.max[1:]

        if self.min:
            if is_string(self.min):
                try:
                    self.min = string_to_float(self.min)
                except ValueError:
                    if self.min[0] == '_':
                        self.min = self.min[1:]


def parse_sub_category(field_section, budget_year, use_puf_not_cps=True):
    output = []
    free_fields = []
    for x in field_section:
        for y, z in x.iteritems():
            section_name = dict(z).get("section_2")
            new_param = {y[y.index('_') + 1:]: TaxCalcParam(y, z, budget_year,
                                                            use_puf_not_cps)}
            if section_name:
                section = next((item for item in output if section_name in item), None)
                if not section:
                    output.append({section_name: [new_param]})
                else:
                    section[section_name].append(new_param)
            else:
                free_fields.append(field_section.pop(field_section.index(x)))
                free_fields[free_fields.index(x)] = new_param
    return output + free_fields


def parse_top_level(ordered_dict):
    output = []
    for x, y in ordered_dict.iteritems():
        section_name = dict(y).get("section_1")
        if section_name:
            section = next((item for item in output if section_name in item), None)
            if not section:
                output.append({section_name: [{x: dict(y)}]})
            else:
                section[section_name].append({x: dict(y)})
    return output


def nested_form_parameters(budget_year=2017, use_puf_not_cps=True,
                           defaults=None):
    # defaults are None unless we are testing
    if defaults is None:
        defaults = taxcalc.Policy.default_data(metadata=True,
                                               start_year=budget_year)
    groups = parse_top_level(defaults)
    for x in groups:
        for y, z in x.iteritems():
            x[y] = parse_sub_category(z, budget_year, use_puf_not_cps)
    return groups

# Create a list of default Behavior parameters
def default_behavior(first_budget_year):

    default_behavior_params = {}
    BEHAVIOR_DEFAULT_PARAMS_JSON = default_taxcalc_data(taxcalc.Behavior,
                                                        metadata=True,
                                                        start_year=first_budget_year)

    for k,v in BEHAVIOR_DEFAULT_PARAMS_JSON.iteritems():
        param = TaxCalcParam(k,v, first_budget_year)
        default_behavior_params[param.nice_id] = param

    return default_behavior_params


# Create a list of default policy
def default_policy(first_budget_year, use_puf_not_cps=True):

    TAXCALC_DEFAULT_PARAMS_JSON = default_taxcalc_data(taxcalc.policy.Policy,
                                                       metadata=True,
                                                       start_year=first_budget_year)

    default_taxcalc_params = {}
    for k,v in TAXCALC_DEFAULT_PARAMS_JSON.iteritems():
        param = TaxCalcParam(k,v, first_budget_year,
                             use_puf_not_cps=use_puf_not_cps)
        default_taxcalc_params[param.nice_id] = param

    TAXCALC_DEFAULT_PARAMS = default_taxcalc_params

    return TAXCALC_DEFAULT_PARAMS


# Debug TaxParams
"""
for k, param in TAXCALC_DEFAULT_PARAMS.iteritems():
    print(' -- ' + k + ' -- ')
    print('TC id:   ' + param.tc_id)
    print('Nice id: ' + param.nice_id)
    print('name:    ' + param.name)
    print('info:    ' + param.info + '\n')

    if param.inflatable:
        field = param.cpi_field
        print(field.id + ' - ' + field.label + ' - ' + str(field.values))
    for field in param.col_fields:
        print(field.id + '   - ' + field.label + ' - ' + str(field.values))

    print('\n')
"""


def rename_keys(rename_dict, map_dict):
    """
    Recursively rename keys in `rename_dict` according to mapping specified
    in `map_dict`

    returns: dict with new keys
    """
    if isinstance(rename_dict, dict):
        for k in rename_dict:
            if k in map_dict:
                new_label = map_dict[k]
            elif k[:-2] in map_dict:
                label = k[:-2]
                year = k[-2:]
                new_label = map_dict[label] + year
            else:
                new_label = k
            rename_dict[new_label] = rename_keys(rename_dict.pop(k), map_dict)
    return rename_dict


def reorder_lists(results, reorder_ix_map, table_names):
    """
    Reorder lists in `results[table_id][bin_label]`. Required for difference
    tables calculated with Tax-Calculator version <0.13.0

    returns: results table with reordered lists in selected tables
    """

    def reorder(disordered):
        reordered = disordered[:]
        for ix in range(len(reorder_ix_map)):
            reordered[reorder_ix_map[ix]] = disordered[ix]
        return reordered

    for table_name in table_names:
        bins = list(results[table_name].keys())
        for ix in range(len(bins)):
            results[table_name][bins[ix]] = reorder(
                results[table_name][bins[ix]]
            )

    return results


def taxcalc_results_to_tables(results, first_budget_year):
    """
    Take various results from dropq, i.e. mY_dec, mX_bin, df_dec, etc
    Return organized and labeled table results for display
    """
    total_row_keys = AGG_ROW_NAMES
    num_years = len(results['aggr_d'][total_row_keys[0]])
    years = list(range(first_budget_year,
                       first_budget_year + num_years))

    tables = {}
    for table_id in results:
        # Debug inputs
        """
        print('\n ----- inputs ------- ')
        print('looking at {0}'.format(table_id))
        if table_id == 'fiscal_tot_diffs':
            print('{0}'.format(results[table_id]))
        else:
            print('{0}'.format(results[table_id].keys()))
        print(' ----- inputs ------- \n')
        """

        if table_id in ['dist1_xdec', 'dist2_xdec']:
            row_keys = TAXCALC_RESULTS_DEC_ROW_KEYS
            row_labels = TAXCALC_RESULTS_DEC_ROW_KEY_LABELS
            col_labels = TAXCALC_RESULTS_MTABLE_COL_LABELS
            col_formats = TAXCALC_RESULTS_MTABLE_COL_FORMATS
            table_data = results[table_id]
            multi_year_cells = True

        elif table_id in ['dist1_xbin', 'dist2_xbin']:
            row_keys = TAXCALC_RESULTS_BIN_ROW_KEYS
            row_labels = TAXCALC_RESULTS_BIN_ROW_KEY_LABELS
            col_labels = TAXCALC_RESULTS_MTABLE_COL_LABELS
            col_formats = TAXCALC_RESULTS_MTABLE_COL_FORMATS
            table_data = results[table_id]
            multi_year_cells = True

        elif table_id in ['diff_itax_xdec', 'diff_ptax_xdec', 'diff_comb_xdec']:
            row_keys = TAXCALC_RESULTS_DEC_ROW_KEYS
            row_labels = TAXCALC_RESULTS_DEC_ROW_KEY_LABELS
            col_labels = TAXCALC_RESULTS_DFTABLE_COL_LABELS
            col_formats = TAXCALC_RESULTS_DFTABLE_COL_FORMATS
            table_data = results[table_id]
            multi_year_cells = True

        elif table_id in ['diff_itax_xbin', 'diff_ptax_xbin', 'diff_comb_xbin']:
            row_keys = TAXCALC_RESULTS_BIN_ROW_KEYS
            row_labels = TAXCALC_RESULTS_BIN_ROW_KEY_LABELS
            col_labels = TAXCALC_RESULTS_DFTABLE_COL_LABELS
            col_formats = TAXCALC_RESULTS_DFTABLE_COL_FORMATS
            table_data = results[table_id]
            multi_year_cells = True

        elif table_id == 'aggr_d':
            # todo - move these into the above TC result param constants
            row_keys = AGG_ROW_NAMES
            row_labels = TAXCALC_RESULTS_TOTAL_ROW_KEY_LABELS
            col_labels = years
            col_formats = [ [1000000000, 'Dollars', 1] for y in years]
            table_data = results[table_id]
            multi_year_cells = False

        elif table_id == 'aggr_1':
            # todo - move these into the above TC result param constants
            row_keys = AGG_ROW_NAMES
            row_labels = TAXCALC_RESULTS_TOTAL_ROW_KEY_LABELS
            col_labels = years
            col_formats = [ [1000000000, 'Dollars', 1] for y in years]
            table_data = results[table_id]
            multi_year_cells = False

        elif table_id == 'aggr_2':
            # todo - move these into the above TC result param constants
            row_keys = AGG_ROW_NAMES
            row_labels = TAXCALC_RESULTS_TOTAL_ROW_KEY_LABELS
            col_labels = years
            col_formats = [ [1000000000, 'Dollars', 1] for y in years]
            table_data = results[table_id]
            multi_year_cells = False
        else:
            raise(ValueError("{} not in expected list of names {}".
                  format(table_id, ','.join(["dist2_xdec", "dist1_xdec",
                                             "diff_itax_xdec", "diff_ptax_xdec",
                                             "diff_comb_xdec", "dist2_xbin",
                                             "dist1_xbin", "diff_itax_xbin",
                                             "diff_itax_xbin", "diff_ptax_xbin",
                                             "diff_comb_xbin", "aggr_d",
                                             "aggr_1", "aggr_2"]))))
        table = {
            'col_labels': col_labels,
            'cols': [],
            'label': TAXCALC_RESULTS_TABLE_LABELS[table_id],
            'rows': [],
            'multi_valued': multi_year_cells
        }

        for col_key, label in enumerate(col_labels):
            table['cols'].append({
                'label': label,
                'divisor': col_formats[col_key][0],
                'units': col_formats[col_key][1],
                'decimals': col_formats[col_key][2],
            })

        col_count = len(col_labels)
        for row_key in row_keys:
            row = {
                'label': row_labels[row_key],
                'cells': []
            }

            for col_key in range(0, col_count):
                cell = {
                    'year_values': {},
                    'format': {
                        'divisor': table['cols'][col_key]['divisor'],
                        'decimals': table['cols'][col_key]['decimals'],
                    }
                }

                if multi_year_cells:
                    for yi, year in enumerate(years):
                        value = table_data["{0}_{1}".format(row_key, yi)][col_key]
                        if value[-1] == "%":
                            value = value[:-1]
                        cell['year_values'][year] = value

                    cell['first_value'] = cell['year_values'][first_budget_year]

                else:
                    value = table_data[row_key][col_key]
                    if value[-1] == "%":
                            value = value[:-1]
                    cell['value'] = value

                row['cells'].append(cell)

            table['rows'].append(row)

        tables[table_id] = table

        # Debug results
        """
        print '\n ----- result ------- '
        print '{0}'.format(table)
        print ' ----- result ------- \n'
        """

    tables['result_years'] = years
    return tables

def format_csv(tax_results, url_id, first_budget_year):
    """
    Takes a dictionary with the tax_results, having these keys:
    [u'mY_bin', u'mX_bin', u'mY_dec', u'mX_dec', u'df_dec', u'df_bin',
    u'fiscal_tot_diffs']
    And then returns a list of list of strings for CSV output. The format
    of the lines is as follows:
    #URL: http://www.ospc.org/taxbrain/ID/csv/
    #aggr_d
    YEAR_0, ... YEAR_K
    val, val, ... val
    #dist1_xdec
    YEAR_0
    col_0, col_1, ..., col_n
    val, val, ..., val
    YEAR_1
    col_0, col_1, ..., col_n
    val, val, ..., val
    ...
    #dist2_xdec
    YEAR_0
    col_0, col_1, ..., col_n
    val, val, ..., val
    YEAR_1
    col_0, col_1, ..., col_n
    val, val, ..., val
    ...
    #diff_itax_xdec
    YEAR_0
    col_0, col_1, ..., col_n
    val, val, ..., val
    YEAR_1
    col_0, col_1, ..., col_n
    val, val, ..., val
    ...
    #dist1_xbin
    YEAR_0
    col_0, col_1, ..., col_n
    val, val, ..., val
    YEAR_1
    col_0, col_1, ..., col_n
    val, val, ..., val
    ...
    #dist2_xbin
    YEAR_0
    col_0, col_1, ..., col_n
    val, val, ..., val
    YEAR_1
    col_0, col_1, ..., col_n
    val, val, ..., val
    ...
    #diff_itax_xbin
    YEAR_0
    col_0, col_1, ..., col_n
    val, val, ..., val
    YEAR_1
    col_0, col_1, ..., col_n
    val, val, ..., val
    ...
    """
    res = []

    #URL
    res.append(["#URL: http://www.ospc.org/taxbrain/" + str(url_id) + "/"])

    #aggr2
    res.append(["#aggr_2"])
    ft = tax_results.get('aggr_d', {})
    yrs = [first_budget_year + i for i in range(0, len(ft['ind_tax']))]
    if yrs:
        res.append(yrs)
    if ft:
        res.append(['payroll_tax'])
        res.append(ft['payroll_tax'])
        res.append(['combined_tax'])
        res.append(ft['combined_tax'])
        res.append(['ind_tax'])
        res.append(ft['ind_tax'])

    #dist1_xdec
    res.append(["#dist1_xdec"])
    mxd = tax_results.get('dist1_xdec', {})
    if mxd:
        for count, yr in enumerate(yrs):
            res.append([yr])
            res.append(TAXCALC_RESULTS_MTABLE_COL_LABELS)
            for row in TAXCALC_RESULTS_DEC_ROW_KEYS:
                res.append(mxd[row+"_" + str(count)])

    #dist2_xdec
    res.append(["#dist2_xdec"])
    myd = tax_results.get('dist2_xdec', {})
    if myd:
        for count, yr in enumerate(yrs):
            res.append([yr])
            res.append(TAXCALC_RESULTS_MTABLE_COL_LABELS)
            for row in TAXCALC_RESULTS_DEC_ROW_KEYS:
                res.append(myd[row+"_" + str(count)])

    #diff_itax_xdec
    res.append(["#diff_itax_xdec"])
    dfd = tax_results.get('diff_itax_xdec', {})
    if dfd:
        for count, yr in enumerate(yrs):
            res.append([yr])
            res.append(TAXCALC_RESULTS_DFTABLE_COL_LABELS)
            for row in TAXCALC_RESULTS_DEC_ROW_KEYS:
                res.append(dfd[row+"_" + str(count)])

    #dist1_xbin
    res.append(["#dist1_xbin"])
    mxb = tax_results.get('mX_bin', {})
    if mxb:
        for count, yr in enumerate(yrs):
            res.append([yr])
            res.append(TAXCALC_RESULTS_MTABLE_COL_LABELS)
            for row in TAXCALC_RESULTS_BIN_ROW_KEYS:
                res.append(mxb[row+"_" + str(count)])

    #dist2_xbin
    res.append(["#dist2_xbin"])
    myb = tax_results.get('mY_bin', {})
    if myb:
        for count, yr in enumerate(yrs):
            res.append([yr])
            res.append(TAXCALC_RESULTS_MTABLE_COL_LABELS)
            for row in TAXCALC_RESULTS_BIN_ROW_KEYS:
                res.append(myb[row+"_" + str(count)])

    #diff_itax_xbin
    res.append(["#diff_itax_xbin"])
    dfb = tax_results.get('diff_itax_xbin', {})
    if dfb:
        for count, yr in enumerate(yrs):
            res.append([yr])
            res.append(TAXCALC_RESULTS_DFTABLE_COL_LABELS)
            for row in TAXCALC_RESULTS_BIN_ROW_KEYS:
                res.append(dfb[row+"_" + str(count)])

    return res
