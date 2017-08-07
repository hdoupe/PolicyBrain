import requests
import time
from all_params_reform import get_formatted_reform

BASE_URL = "http://127.0.0.1:8000/taxbrain/"
# BASE_URL = "http://ospc-taxes7.herokuapp.com/taxbrain/"
MINI_REFORM = {u'EITC_rt_0': 0.4,
               u'EITC_rt_1': 0.7,
               u'EITC_rt_2': 0.8,
               u'EITC_rt_3': 1.5}

DATA = {u'start_year': unicode(2017), u'csrfmiddlewaretoken': None,
        u'has_errors': [u'False']}


def get_session(url=BASE_URL):
    session = requests.Session()

    session.get(BASE_URL)
    # print(session.cookies)
    csrftoken = session.cookies['csrftoken']
    # print(csrftoken)

    return session, csrftoken


def get_data(reform=None):
    """read taxbrain styled reform"""
    # if reform is None:
    # DATA.update(MINI_REFORM)
    # return DATA
    # else:
    # at some point read in json reform
    DATA.update(get_formatted_reform())
    return DATA


def post_reform(session, data, url=BASE_URL):
    response = session.post(BASE_URL, data=data)

    # assert response.status_code == 200
    print("RESPONSE", response)
    print(response)
    # print(response.text)
    print("URL", response.url)

    print("DICT", dir(response))

    url = response.url

    pk = url[:-1].split('/')[-1]

    unique_url = BASE_URL + str(pk)
    print ('unique_url', unique_url)

    return session, pk

# def wait(session, pk):
#     time.sleep(10)
#
#     print ('unique_url', unique_url)
#     result_response = s.get(unique_url)
#
#     print(result_response)
#     print(dir(result_response))
#     print(result_response.text)
#     print(result_response.status_code)
#     print(result_response.json)
#     result_json = result_response.json()
#     print(result_json)
#
#     while result_json['status_code'] == 202:
#         result_response = s.get(unique_url)
#         result_json = result_response.json()
#         print(result_response)
#         print(result_json)
#         time.sleep(5)
#
# def read_csv(session, pk):
#     # time.sleep(300)
#     print(result_json)
#     print('now getting csv?')
#     csv_url = unique_url + 'output.csv/'
#     r = s.get(csv_url)
#
#     print(r)
#     print(r.text)


if __name__ == "__main__":
    session, csrftoken = get_session()
    data = get_data()
    print(data)
    data[u'csrfmiddlewaretoken'] = csrftoken
    session, pk = post_reform(session, data)
