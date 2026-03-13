from django.shortcuts import render,redirect
from django.contrib.auth import authenticate, login, logout
from .forms import LoginForm,RegisterForm
from django.contrib.auth.models import User

# Create your views here.
def login_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard")  #Redirect to home if already logged in
    form=LoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        username=form.cleaned_data.get("username")
        password=form.cleaned_data.get("password")
        user=authenticate(request,username=username,password=password)
        if user is not None:
            login(request,user)
            return redirect("dashboard")
        else:
            form.add_error(None,"Invalid username or password")
    return render(request,"accounts/login.html",{"form":form})
        
def logout_view(request):
    logout(request)
    return redirect("login")

def register_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard")  #Redirect to home if already logged in
    # Registration logic will go here

    form=RegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        username=form.cleaned_data.get("username")
        email=form.cleaned_data.get("email")
        password=form.cleaned_data.get("password1")
        user=User.objects.create_user(username=username,email=email,password=password)
        login(request,user)
        return redirect("dashboard")
    return render(request,"accounts/register.html",{"form":form})

