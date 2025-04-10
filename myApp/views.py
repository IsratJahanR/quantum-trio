from django.http import HttpResponse
from django.shortcuts import render

# Create your views here.


def home(request):
    return render(request, 'app\home.html')


def contact_us(request):
    return render(request, 'app\contact_us.html')


def service(request):
    return render(request, 'app\service.html')


def book_now(request):
    return render(request, 'app\book_now.html')


def location(request):
    return render(request, 'app\location.html')


def explore_by_item(request):
    return render(request, 'app\explore_by_items.html')

#For Salon Profile
def view_salon_profile(request):
    return render(request, 'app\saloon_profile\dashboard.html')

#For Salon Deshboard
def view_dash_board(request):
    return render(request, 'app\salon_dashboard\index.html')
