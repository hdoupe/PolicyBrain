from taxcalc import Policy, Calculator
import tempfile, os


def convert_int_key(user_mods):
    for key in user_mods:
        if hasattr(key, 'isdigit') and key.isdigit():
            user_mods[int(key)] = user_mods.pop(key)
    return user_mods


def taxio_reform_formatter(user_mods):
    reform_mods = user_mods['reform']
    reform_tmp = tempfile.NamedTemporaryFile(delete=False)
    reform_tmp.write(reform_mods)
    reform_tmp.close()

    assump_mods = user_mods['assumptions']
    if assump_mods:
        assump_tmp = tempfile.NamedTemporaryFile(delete=False)
        assump_tmp.write(assump_mods)
        assump_tmp.close()
        assumptions = assump_tmp.name
    else:
        assumptions = None

    user_reform = Calculator.read_json_param_files(reform_tmp.name, assumptions)
    if not 'gdp_elasticity' in user_reform:
        user_reform['gdp_elasticity'] = {}
    os.remove(reform_tmp.name)
    if assump_mods:
        os.remove(assump_tmp.name)
    policy = user_reform.get('policy') or {}
    user_reform['policy'] = convert_int_key(policy)
    return user_reform
