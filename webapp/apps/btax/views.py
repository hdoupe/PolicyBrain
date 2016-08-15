from __future__ import print_function

from django.shortcuts import render

# Create your views here.
def personal_results(request):
    init_context = {
    }
    return render(request, 'btax/input_form.html', init_context)
