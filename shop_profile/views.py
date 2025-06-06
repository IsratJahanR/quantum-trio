import json
from django.db.models import Q
from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt, csrf_protect
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import get_user_model
from django.utils.safestring import mark_safe
from django.utils import timezone
from django.utils.timezone import make_aware,now
from datetime import datetime, date, timedelta, timezone as tz
from django.contrib import messages
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.db.models import F, ExpressionWrapper, DateTimeField
from django.db.models import Value, CharField, BooleanField, Case, When
from django.db.models.functions import Concat, Cast
from calendar import HTMLCalendar
from booking.models import BookingSlot
from my_app.models import Item
from shop_profile.models import ShopGallery, ShopWorker, ShopService, ShopNotification,ShopSchedule
from my_app.models import District,Upazilla,Service
from django.contrib.postgres.aggregates import ArrayAgg
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from collections import OrderedDict
from decimal import Decimal
# variable
user = get_user_model()
booking_not_found = "Booking not found."

@csrf_protect
@login_required
@require_http_methods(["GET"])
def profile(request):
    """previous 15 days response data"""
    shop=request.user.shop_profile
    response_data = [
        {
            "date": (datetime.now() - timedelta(days=i)).strftime("%d %b"),
            "value": BookingSlot.objects.filter(
                        shop=shop,
                        status='completed',
                        date=(datetime.now() - timedelta(days=i)).date()
                    ).count()
        }
        for i in range(14, -1, -1)
    ]
    print(response_data)
    
    """monthly data """
    current_year = now().year
    current_month = datetime.now().month
    months = OrderedDict(
        (datetime(2000, m, 1).strftime('%b'), Decimal('0.00')) 
        for m in range(1, current_month + 1)
    )
    # Get completed bookings for this shop this year
    completed_bookings = BookingSlot.objects.filter(
        shop=shop,
        status='completed',
        date__year=current_year
    ).select_related('item')
    # Map item_id to price for this shop
    price_map = {
        service.item_id: service.price
        for service in ShopService.objects.filter(shop=shop)
    }
    # sum up 
    for booking in completed_bookings:
        month_name = booking.date.strftime('%b')
        price = price_map.get(booking.item_id, Decimal('0.00'))
        months[month_name] += price
    # convert to ordered dict
    values = [float(val) for val in months.values()] 
    monthly_data = [
        {"month": month, "value": value}
        for month, value in zip(months, values)
    ]
    # print(monthly_data)
    
    """Total customers count"""
    total_customer=BookingSlot.objects.filter(shop=shop,status='completed').count()
    
    """New Customers (This Month)"""
    now_time = now()
    start_of_month = now_time.replace(day=1)
    # Get users who completed bookings this month at the current shop
    completed_this_month_users = BookingSlot.objects.filter(
            shop=shop,
            status='completed',
            created_at__gte=start_of_month
        ).values_list('user', flat=True).distinct()
    
    # Remove users who had any completed booking *before* this month
    old_customers = BookingSlot.objects.filter(
        shop=shop,
        status='completed',
        created_at__lt=start_of_month,
        user__in=completed_this_month_users
    ).values_list('user', flat=True).distinct()
    
    # Exclude old customers from the current month's list
    new_customer= completed_this_month_users.exclude(id__in=old_customers).count()
    
    context={
        'response_data':response_data,
        'monthly_data':monthly_data,
        'total_customer':total_customer,
        'new_customer':new_customer
    }
    return render(request, "app/salon_dashboard/index.html",context)

@csrf_protect
@login_required
@require_http_methods(["GET", "POST"])
def gallery(request):
    message = ""
    if request.method == "POST":
        if request.FILES:
            img = request.FILES.get("image")
            shop = request.user.shop_profile
            gallery = ShopGallery.objects.create(shop=shop, image=img)
            gallery.save()
            message = "success"
        if "delete_image" in request.POST:
            img_id = request.POST.get("img_id")
            image = get_object_or_404(
                ShopGallery, id=img_id, shop=request.user.shop_profile
            )
            image.image.delete()
            image.delete()

    img = ShopGallery.objects.filter(shop=request.user.shop_profile)
    return render(
        request,
        "app/salon_dashboard/saloon-gallery.html",
        {"image": img, "message": message},
    )

@csrf_protect
@login_required
@require_http_methods(["GET"])
def calender(request):
    month = datetime.now().month
    year = datetime.now().year

    if (
        request.method == "GET"
        and request.GET.get("month") is not None
        and request.GET.get("year") is not None
    ):
        month = int(request.GET.get("month"))
        year = int(request.GET.get("year"))
    print(month, type(int(year)))
    cal = HTMLCalendar().formatmonth(year, month)

    return render(
        request,
        "app/salon_dashboard/saloon-calender.html",
        {"cal": cal, "month": month, "year": year},
    )

@csrf_protect
@login_required
@require_http_methods(["GET"])
def slots(request):
    today = date.today()
    if request.method == "GET" and request.GET.get("date") is not None:
        today = datetime.strptime(request.GET.get("date"), "%Y-%m-%d")

    print(today)

    # adding 6 hours for the difference of timezone
    # this is to check wheather the time has passed or not of the following booking if passed then
    # the report button will appear so that the shop owner can report if needed
    updated_time = timezone.now() + timedelta(hours=6)
    current_time = datetime.strptime(
        updated_time.time().strftime("%H:%M:%S"), "%H:%M:%S"
    ).time()  # for removing the millisecond
    current_date = updated_time.date()
    current_datetime = datetime.combine(current_date, current_time)
    current_datetime = current_datetime.replace(tzinfo=tz.utc)
    worker = ShopWorker.objects.filter(shop=request.user.shop_profile)
    shop_worker = []
    for i in worker:
        temp = {
            "worker": i,
            "booking_slots": BookingSlot.objects.filter(worker=i, date=today)
            .exclude(Q(status="canceled"))
            .annotate(
                booking_datetime=ExpressionWrapper(
                    Cast(
                        Concat(
                            Cast(
                                F("date"), output_field=CharField()
                            ),  # Convert DateField to CharField
                            Value(" "),  # Space separator
                            Cast(
                                F("time"), output_field=CharField()
                            ),  # Convert TimeField to CharField
                        ),
                        output_field=DateTimeField(),  # Convert final result to DateTimeField
                    ),
                    output_field=DateTimeField(),
                ),
                is_expired=Case(
                    When(booking_datetime__lt=current_datetime, then=Value(True)),
                    default=Value(False),
                    output_field=BooleanField(),
                ),
            ),
        }
        for slot in temp["booking_slots"]:
            print(slot.booking_datetime, current_datetime, slot.is_expired)
        shop_worker.append(temp)
    return render(
        request,
        "app/salon_dashboard/booking-slots.html",
        {"shop_worker": shop_worker, "today": current_datetime},
    )

"""Cancel booking"""
@csrf_protect
@login_required
@require_http_methods(["POST"])
def reject_booking(request):
    if request.method == "POST":
        data = json.loads(request.body)
        booking_id = data.get("booking_id")

        try:
            booking = BookingSlot.objects.get(id=booking_id)
            
            # Combine date and time into a single datetime object
            booking_datetime = datetime.combine(booking.date, booking.time)
            booking_datetime = make_aware(booking_datetime)  # make timezone aware
            print("booking time:",booking_datetime)
            # Check if less than 24 hours remaining
            now = datetime.now().astimezone()
            print("Now: ",now)
            print("diff: ",booking_datetime - now)
            if booking_datetime - now < timedelta(hours=30): #we added extra 6 hours because of our timezone is +6:00 and the server time is 6 hours fast
                return JsonResponse({
                    "success": False,
                    "message": "Cannot cancel booking within 24 hours of the appointment time."
                })

            booking.status = "canceled"
            booking.save()
            return JsonResponse({"success": True, "message": "Booking canceled."})

        except BookingSlot.DoesNotExist:
            return JsonResponse({"success": False, "message": "Booking not found."})

"""retrieval of booking-details of a booking"""

@csrf_protect
@login_required
@require_http_methods(["POST"])
def booking_details(request):
    if request.method == "POST":
        data = json.loads(request.body)
        booking_id = data.get("booking_id")
        try:
            booking = BookingSlot.objects.get(id=booking_id)
            service = ShopService.objects.get(shop=booking.shop, item=booking.item)
            print(service)
            return JsonResponse(
                {
                    "success": True,
                    "details": {
                        "full_name": f"{booking.user.first_name} {booking.user.last_name}",
                        "shop_name": booking.shop.shop_name,
                        "worker": booking.worker.name,
                        "item_name": booking.item.name,
                        "item_price": str(service.price),
                        "booked_time": booking.time.strftime("%I:%M %p"),
                        "booked_date": booking.date.strftime("%d-%m-%Y"),
                        "status": booking.status,
                        "booking_time": booking.time.strftime("%I:%M %p"),
                    },
                }
            )
        except BookingSlot.DoesNotExist:
            return JsonResponse({"success": False, "message": booking_not_found})

@csrf_protect
@login_required
@require_http_methods(["POST"])
def update_status(request):
    if request.method == "POST":
        data = json.loads(request.body)
        booking_id = data.get("booking_id")
        try:
            booking = BookingSlot.objects.get(id=booking_id)  # Get the booking object
            # Combine the booking date and time
            booking_datetime = datetime.combine(booking.date, booking.time)

            # adding 6 hours for the difference of timezone
            updated_time = timezone.now() + timedelta(hours=6)
            current_time = datetime.strptime(
                updated_time.time().strftime("%H:%M:%S"), "%H:%M:%S"
            ).time()  # for removing the millisecond
            current_date = updated_time.date()
            today = datetime.combine(current_date, current_time)

            # Check if the current time is greater than the booking date and time
            if today > booking_datetime:
                # Only update the status if the current time is after the booked time
                booking.shop_end = True
                booking.save()
                return JsonResponse(
                    {
                        "success": True,
                        "details": {
                            "message": "You have successfully marked as completed!"
                        },
                    }
                )
            else:
                return JsonResponse(
                    {
                        "success": False,
                        "message": "The booking time has not yet arrived.",
                    }
                )

        except BookingSlot.DoesNotExist:
            return JsonResponse({"success": False, "message": booking_not_found})

@csrf_protect
@login_required
@require_http_methods(["GET"])
def message(request):
    return render(request, "app/salon_dashboard/message.html")

@csrf_protect
@login_required
@require_http_methods(["GET","POST"])
def staffs(request):
    if request.method == "POST":
        worker_id = request.POST.get("id")
        name = request.POST.get("name")
        email = request.POST.get("email")
        phone = request.POST.get("phone")
        experience = request.POST.get("experience")
        expertise_ids = request.POST.getlist("expertise")
        profile_pic = request.FILES.get("profile_pic")
        """ Fetch expertise items in one query """
        expertise_items = Item.objects.filter(id__in=expertise_ids)
        try:
            worker = ShopWorker.objects.get(id=worker_id)
            worker.name = name
            worker.email = email
            worker.phone = phone
            worker.experience = experience
            if expertise_items.exists():  # Only update if there are valid expertise items
                worker.expertise.set(expertise_items)
            if profile_pic:  # Only update profile_pic if a new file is uploaded delete first then upload
                if worker.profile_pic:
                    worker.profile_pic.delete(save=False)
                worker.profile_pic = profile_pic
            worker.save()
            messages.success(request,"Worker details updated Successfully.")
            
        except (ValueError, TypeError):
            messages.error(request,"Please enter a valid number of years.")
        except ShopWorker.DoesNotExist:
            messages.error(request,"Worker doesn't Exist.")

    workers = ShopWorker.objects.filter(shop=request.user.shop_profile)
    items = ShopService.objects.filter(shop=request.user.shop_profile)

    return render(
        request,
        "app/salon_dashboard/staffs.html",
        {"shop_worker": workers, "items": items},
    )

@csrf_protect
@login_required
@require_http_methods(["POST"])
def add_worker(request):
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        email = request.POST.get("email", "").strip()
        phone = request.POST.get("phone", "").strip()
        experience = request.POST.get("experience", "0").strip()
        expertise = request.POST.getlist("expertise")  # Multiple selections
        profile_pic = request.FILES.get("profile_pic")

        # Validate inputs
        if not name or not phone or not expertise:
            messages.error(request, "Name, Mobile, and Expertise are required.")
            return redirect("add_worker")
        if email:
            try:
                validate_email(email)
            except ValidationError:
                messages.error(request, "Invalid email format.")
                return redirect("add_worker")

        # Convert experience to an integer safely
        try:
            experience = int(float(experience))  # Handles decimal input
        except ValueError:
            messages.error(request, "Experience must be a number.")
            return redirect("add_worker")
        worker = ShopWorker.objects.create(
            name=name,
            email=email,
            phone=phone,
            experience=experience,
            profile_pic=profile_pic,
            shop=request.user.shop_profile,
        )
        worker.expertise.add(*expertise)
        messages.success(request, "Worker added successfully!")
        return redirect("shop_staffs")
    return render(request, "staffs")

@csrf_protect
@login_required
@require_http_methods(["GET"])
def customers(request):
    booking = BookingSlot.objects.filter(shop=request.user.shop_profile).order_by(
        "-date", "-time"
    )
    print(booking)
    return render(request, "app/salon_dashboard/customers.html", {"bookings": booking})

@csrf_protect
@login_required
@require_http_methods(["GET"])
def review(request):
    return render(request, "app/salon_dashboard/reviews.html")

@csrf_protect
@login_required
@require_http_methods(["GET"])
def notification(request):
    notification = ShopNotification.objects.filter(
        shop=request.user.shop_profile
    ).order_by("-created_at")
    return render(
        request,
        "app/salon_dashboard/notifications.html",
        {"notifications": notification},
    )

@csrf_protect
@login_required
@require_http_methods(["GET"])
def setting(request):
    return render(request, "app/salon_dashboard/settings.html")

@csrf_protect
@login_required
@require_http_methods(["GET","POST"])
def basic_update(request):
    shop=request.user.shop_profile
    user=request.user
    district = District.objects.all().values('id', 'name')
    upazilla = Upazilla.objects.values('district__name').annotate(upazilla_names=ArrayAgg('name'))
    if request.method == 'POST':
        try:
            # Get updated data from the form
            shop.shop_name = request.POST.get('shop_name', shop.shop_name)
            shop.shop_title = request.POST.get('shop_title', shop.shop_title)
            shop.shop_info = request.POST.get('shop_info', shop.shop_info)
            shop.shop_owner = request.POST.get('shop_owner', shop.shop_owner)
            shop.mobile_number = request.POST.get('mobile_number', shop.mobile_number)
            shop.shop_website = request.POST.get('shop_website', shop.shop_website)
            shop.gender = request.POST.get('gender', shop.gender)
            shop.status = request.POST.get('status', shop.status) == 'true'
            shop.shop_state = request.POST.get('shop_state', shop.shop_state)
            shop.shop_city = request.POST.get('shop_city', shop.shop_city)
            shop.shop_area = request.POST.get('shop_area', shop.shop_area)
            
            # Landmarks (optional fields)
            shop.shop_landmark_1 = request.POST.get('landmark_1', shop.shop_landmark_1)
            shop.shop_landmark_2 = request.POST.get('landmark_2', shop.shop_landmark_2)
            shop.shop_landmark_3 = request.POST.get('landmark_3', shop.shop_landmark_3)
            shop.shop_landmark_4 = request.POST.get('landmark_4', shop.shop_landmark_4)
            shop.shop_landmark_5 = request.POST.get('landmark_5', shop.shop_landmark_5)

            # Shop image (if uploaded)
            if 'shop_picture' in request.FILES:
                shop.shop_picture = request.FILES['shop_picture'] 
            shop.save()
            messages.success(request, "Shop profile updated successfully.")
            print("Done")

        except Exception as e:
            messages.error(request, f"Failed to update shop: {str(e)}")
            print("error2")

    else:
        print("Error1")
        
    print(shop.gender)
    return render(request, "app/salon_dashboard/update_basic.html",{'user':user,'shop':shop,'district':list(district),'Upazilla':list(upazilla)})

@csrf_protect
@login_required
@require_http_methods(["GET"])
def services_update(request):
    service=Service.objects.all().values('id', 'name')
    return render(
        request,
        "app/salon_dashboard/update-services.html",
        {'services':service}
    )

@csrf_protect
@login_required
@require_http_methods(["GET","POST"])
def schedule_update(request):
    shop=request.user.shop_profile
    if request.method == 'POST':
        schedule_data = request.POST  # QueryDict
        for day in ["Saturday", "Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]:
            start_time = schedule_data.get(f"schedule[{day}][start]", "").strip()
            end_time = schedule_data.get(f"schedule[{day}][end]", "").strip()
            # Only save the day if it has valid start or end time
            if start_time < end_time:
                shop_schedule = ShopSchedule.objects.get(shop=shop, day_of_week=day)
                shop_schedule.start = start_time
                shop_schedule.end = end_time
                shop_schedule.save()
                print("ok")
            else:
                print("Not Valid")
    schedule=ShopSchedule.objects.filter(shop=shop)
    schedule_dict = {
        s.day_of_week: {
            'start': s.start.strftime('%H:%M'),  # Convert to string in 'HH:MM' format
            'end': s.end.strftime('%H:%M')       # Convert to string in 'HH:MM' format
        }
        for s in schedule
    }   
    return render(request, 'app/salon_dashboard/update_schedule.html', {
        'days_of_week':{'Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'},
        'schedule_dict':schedule_dict  # unpack into template context
    })
