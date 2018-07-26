from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse

import json
from django.utils import timezone
from .models import CoreRun
from .compute import Compute, JobFailError
from ..formatters import get_version
from ..taxbrain.views import TAXCALC_VERSION, WEBAPP_VERSION, dropq_compute
from ..taxbrain.param_formatters import to_json_reform
from ..taxbrain.models import TaxSaveInputs
from django.shortcuts import (render, render_to_response, get_object_or_404,
                              redirect)
from django.template.context import RequestContext


def output_detail(request, pk, model_class=CoreRun):
    """
    This view is the single page of diplaying a progress bar for how
    close the job is to finishing, and then it will also display the
    job results if the job is done. Finally, it will render a 'job failed'
    page if the job has failed.

    Cases:
        case 1: result is ready and successful

        case 2: model run failed

        case 3: query results
          case 3a: all jobs have completed
          case 3b: not all jobs have completed
    """
    model = get_object_or_404(model_class, uuid=pk)

    if model.renderable_outputs:
        context = get_result_context(model, request)
        return render(request, 'taxbrain/results.html', context)
    elif model.error_text:
        return render(request, 'taxbrain/failed.html',
                      {"error_msg": model.error_text})
    else:
        job_ids = model.job_ids
        try:
            jobs_ready = dropq_compute.results_ready(job_ids)
        except JobFailError as jfe:
            return render_to_response('taxbrain/failed.html')
        if any(j == 'FAIL' for j in jobs_ready):
            failed_jobs = [sub_id for (sub_id, job_ready)
                           in zip(job_ids, jobs_ready)
                           if job_ready == 'FAIL']

            # Just need the error message from one failed job
            error_msgs = dropq_compute.get_results([failed_jobs[0]],
                                                   job_failure=True)
            if error_msgs:
                error_msg = error_msgs[0]
            else:
                error_msg = "Error: stack trace for this error is unavailable"
            val_err_idx = error_msg.rfind("Error")
            error_contents = error_msg[val_err_idx:].replace(" ", "&nbsp;")
            model.error_text = error_contents
            model.save()
            return render(request, 'taxbrain/failed.html',
                          {"error_msg": error_contents})

        if all(j == 'YES' for j in jobs_ready):
            results = dropq_compute.get_results(job_ids)
            model.renderable_outputs = results['renderable']
            model.download_only_outputs = results['download_only']
            model.creation_date = timezone.now()
            model.save()
            context = get_result_context(model, request)
            return render(request, 'taxbrain/results.html', context)
        else:
            if request.method == 'POST':
                # if not ready yet, insert number of minutes remaining
                exp_comp_dt = model.exp_comp_datetime
                utc_now = timezone.now()
                dt = exp_comp_dt - utc_now
                exp_num_minutes = dt.total_seconds() / 60.
                exp_num_minutes = round(exp_num_minutes, 2)
                exp_num_minutes = exp_num_minutes if exp_num_minutes > 0 else 0
                if exp_num_minutes > 0:
                    return JsonResponse({'eta': exp_num_minutes}, status=202)
                else:
                    return JsonResponse({'eta': exp_num_minutes}, status=200)

            else:
                context = {'eta': '100'}
                return render_to_response(
                    'taxbrain/not_ready.html',
                    context,
                    context_instance=RequestContext(request)
                )


def get_result_context(model, request):
    inputs = model.inputs
    first_year = inputs.first_year
    quick_calc = inputs.quick_calc
    created_on = inputs.creation_date

    is_from_file = not inputs.raw_input_fields

    if (inputs.json_text is not None and
        (inputs.json_text.raw_reform_text or
         inputs.json_text.raw_assumption_text)):
        reform_file_contents = inputs.json_text.raw_reform_text
        reform_file_contents = reform_file_contents.replace(" ", "&nbsp;")
        assump_file_contents = inputs.json_text.raw_assumption_text
        assump_file_contents = assump_file_contents.replace(" ", "&nbsp;")
    elif inputs.input_fields is not None:
        reform = to_json_reform(first_year, inputs.input_fields)
        reform_file_contents = json.dumps(reform, indent=4)
        assump_file_contents = '{}'
    else:
        reform_file_contents = None
        assump_file_contents = None

    is_registered = (hasattr(request, 'user') and
                     request.user.is_authenticated())

    context = {
        'locals': locals(),
        'unique_url': model,
        'created_on': created_on,
        'first_year': first_year,
        'quick_calc': quick_calc,
        'is_registered': is_registered,
        'is_micro': True,
        'reform_file_contents': reform_file_contents,
        'assump_file_contents': assump_file_contents,
        'dynamic_file_contents': None,
        'is_from_file': is_from_file,
        'allow_dyn_links': not is_from_file,
        'results_type': "static",
        'renderable': model.renderable_outputs.values()
        # 'download_only': model.download_only_outputs.values()
    }

    return context
