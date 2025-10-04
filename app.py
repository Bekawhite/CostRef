import streamlit as st
import hashlib
import sqlalchemy as db
from sqlalchemy import create_engine, Column, String, Integer, DateTime, JSON, Text, Boolean, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
from datetime import datetime, timedelta
import pandas as pd
import plotly.express as px
import pydeck as pdk
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import numpy as np
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import inch
import secrets
import string
from dotenv import load_dotenv
import time
import threading
import math

load_dotenv()

# =============================================================================
# ENHANCED CONFIGURATION WITH COST TRACKING
# =============================================================================
class Config:
    DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///hospital_referral.db')
    SMTP_SERVER = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
    SMTP_PORT = int(os.getenv('SMTP_PORT', 587))
    SMTP_USERNAME = os.getenv('SMTP_USERNAME')
    SMTP_PASSWORD = os.getenv('SMTP_PASSWORD')
    DEFAULT_LATITUDE = -0.0916
    DEFAULT_LONGITUDE = 34.7680
    DEFAULT_ZOOM = 10
    PAGE_TITLE = "Kisumu County Hospital Referral System"
    PAGE_ICON = "🏥"
    LAYOUT = "wide"
    GOOGLE_MAPS_API_KEY = os.getenv('GOOGLE_MAPS_API_KEY', '')
    NOTIFICATION_CHECK_INTERVAL = 30  # seconds
    LOCATION_UPDATE_INTERVAL = 10     # seconds
    
    # NEW: Cost tracking configurations
    FUEL_PRICE_PER_LITER = 180  # Kenyan Shillings per liter
    AVERAGE_FUEL_CONSUMPTION = 0.12  # Liters per kilometer for ambulances
    BASE_OPERATING_COST_PER_KM = 50  # KSh per km (maintenance, depreciation, etc.)
    FUEL_TANK_CAPACITY = 80  # Liters - typical ambulance fuel tank

# =============================================================================
# ENHANCED DATABASE MODELS WITH COST TRACKING
# =============================================================================
Base = declarative_base()

class Patient(Base):
    __tablename__ = 'patients'
    patient_id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    age = Column(Integer, nullable=False)
    condition = Column(String, nullable=False)
    referring_hospital = Column(String, nullable=False)
    receiving_hospital = Column(String, nullable=False)
    referring_physician = Column(String, nullable=False)
    receiving_physician = Column(String)
    notes = Column(Text)
    vital_signs = Column(JSON)
    medical_history = Column(Text)
    current_medications = Column(Text)
    allergies = Column(Text)
    referral_time = Column(DateTime, default=datetime.utcnow)
    status = Column(String, default='Referred')
    assigned_ambulance = Column(String)
    created_by = Column(String)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    referring_hospital_lat = Column(Float)
    referring_hospital_lng = Column(Float)
    receiving_hospital_lat = Column(Float)
    receiving_hospital_lng = Column(Float)
    pickup_notification_sent = Column(Boolean, default=False)
    enroute_notification_sent = Column(Boolean, default=False)
    
    # NEW: Cost tracking fields
    trip_distance = Column(Float)  # Distance for this specific trip
    trip_fuel_cost = Column(Float)  # Fuel cost for this trip
    trip_cost_savings = Column(Float, default=0.0)  # Savings from efficient routing

class Ambulance(Base):
    __tablename__ = 'ambulances'
    ambulance_id = Column(String, primary_key=True)
    current_location = Column(String)
    latitude = Column(Float)
    longitude = Column(Float)
    status = Column(String, default='Available')
    driver_name = Column(String)
    driver_contact = Column(String)
    current_patient = Column(String)
    destination = Column(String)
    route = Column(JSON)
    start_time = Column(DateTime)
    current_step = Column(Integer, default=0)
    mission_complete = Column(Boolean, default=False)
    estimated_arrival = Column(DateTime)
    last_location_update = Column(DateTime, default=datetime.utcnow)
    
    # ENHANCED: Fuel and cost tracking
    fuel_level = Column(Float, default=100.0)  # Added fuel level (percentage)
    fuel_consumption_rate = Column(Float, default=0.12)  # Fuel consumption per km in liters
    total_fuel_cost = Column(Float, default=0.0)  # Total fuel cost incurred in KSh
    total_distance_traveled = Column(Float, default=0.0)  # Total distance in km
    cost_savings = Column(Float, default=0.0)  # Cost savings from efficient routing

class Referral(Base):
    __tablename__ = 'referrals'
    id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(String, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    status = Column(String, default='Ambulance Dispatched')
    ambulance_id = Column(String)
    created_by = Column(String)

class HandoverForm(Base):
    __tablename__ = 'handover_forms'
    id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(String, nullable=False)
    patient_name = Column(String)
    age = Column(Integer)
    condition = Column(String)
    referring_hospital = Column(String)
    receiving_hospital = Column(String)
    referring_physician = Column(String)
    receiving_physician = Column(String)
    transfer_time = Column(DateTime, default=datetime.utcnow)
    vital_signs = Column(JSON)
    medical_history = Column(Text)
    current_medications = Column(Text)
    allergies = Column(Text)
    notes = Column(Text)
    ambulance_id = Column(String)
    created_by = Column(String)

class Communication(Base):
    __tablename__ = 'communications'
    id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(String)
    ambulance_id = Column(String)
    sender = Column(String)
    receiver = Column(String)
    message = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow)
    message_type = Column(String)  # 'driver_hospital', 'hospital_hospital', 'system'

class LocationUpdate(Base):
    __tablename__ = 'location_updates'
    id = Column(Integer, primary_key=True, autoincrement=True)
    ambulance_id = Column(String)
    latitude = Column(Float)
    longitude = Column(Float)
    location_name = Column(String)
    timestamp = Column(DateTime, default=datetime.utcnow)
    patient_id = Column(String)

# =============================================================================
# ENHANCED DATABASE SERVICE WITH COST METHODS
# =============================================================================
class Database:
    def __init__(self):
        if os.getenv('DATABASE_URL'):
            self.engine = create_engine(os.getenv('DATABASE_URL'))
        else:
            self.engine = create_engine('sqlite:///hospital_referral.db')
        Base.metadata.create_all(self.engine)
        Session = sessionmaker(bind=self.engine)
        self.session = Session()
    
    def add_patient(self, patient_data):
        if 'patient_id' not in patient_data:
            patient_data['patient_id'] = f"PAT{secrets.token_hex(4).upper()}"
        
        patient = Patient(**patient_data)
        self.session.add(patient)
        self.session.commit()
        return patient
    
    def get_available_ambulances(self):
        return self.session.query(Ambulance).filter(Ambulance.status == 'Available').all()
    
    def update_ambulance_status(self, ambulance_id, status, patient_id=None):
        ambulance = self.session.query(Ambulance).filter(Ambulance.ambulance_id == ambulance_id).first()
        if ambulance:
            ambulance.status = status
            if patient_id:
                ambulance.current_patient = patient_id
            self.session.commit()
    
    def get_patient_by_id(self, patient_id):
        return self.session.query(Patient).filter(Patient.patient_id == patient_id).first()
    
    def get_all_patients(self):
        return self.session.query(Patient).all()
    
    def get_all_ambulances(self):
        return self.session.query(Ambulance).all()
    
    def add_referral(self, referral_data):
        referral = Referral(**referral_data)
        self.session.add(referral)
        self.session.commit()
        return referral
    
    def add_handover_form(self, handover_data):
        handover = HandoverForm(**handover_data)
        self.session.add(handover)
        self.session.commit()
        return handover
    
    def add_communication(self, communication_data):
        communication = Communication(**communication_data)
        self.session.add(communication)
        self.session.commit()
        return communication
    
    def get_communications_for_patient(self, patient_id):
        return self.session.query(Communication).filter(Communication.patient_id == patient_id).order_by(Communication.timestamp.desc()).all()
    
    def get_communications_for_ambulance(self, ambulance_id):
        return self.session.query(Communication).filter(Communication.ambulance_id == ambulance_id).order_by(Communication.timestamp.desc()).all()
    
    def add_location_update(self, location_data):
        location_update = LocationUpdate(**location_data)
        self.session.add(location_update)
        self.session.commit()
        return location_update
    
    def get_latest_location(self, ambulance_id):
        return self.session.query(LocationUpdate).filter(
            LocationUpdate.ambulance_id == ambulance_id
        ).order_by(LocationUpdate.timestamp.desc()).first()
    
    def find_nearest_ambulance(self, hospital_lat, hospital_lng, min_fuel_level=20.0):
        available_ambulances = self.get_available_ambulances()
        if not available_ambulances:
            return None
        
        nearest_ambulance = None
        min_distance = float('inf')
        
        for ambulance in available_ambulances:
            if ambulance.fuel_level < min_fuel_level:
                continue
                
            if ambulance.latitude is not None and ambulance.longitude is not None:
                distance = self.calculate_distance(
                    hospital_lat, hospital_lng, 
                    ambulance.latitude, ambulance.longitude
                )
                if distance < min_distance:
                    min_distance = distance
                    nearest_ambulance = ambulance
        
        return nearest_ambulance
    
    def calculate_distance(self, lat1, lon1, lat2, lon2):
        R = 6371  # Earth radius in kilometers
        
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        
        a = (math.sin(dlat/2) * math.sin(dlat/2) + 
             math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * 
             math.sin(dlon/2) * math.sin(dlon/2))
        
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        distance = R * c
        
        return distance
    
    def update_ambulance_fuel(self, ambulance_id, distance_km=None, new_fuel_level=None):
        ambulance = self.session.query(Ambulance).filter(Ambulance.ambulance_id == ambulance_id).first()
        if ambulance:
            if distance_km is not None:
                fuel_used = distance_km * ambulance.fuel_consumption_rate
                ambulance.fuel_level = max(0, ambulance.fuel_level - fuel_used)
            elif new_fuel_level is not None:
                ambulance.fuel_level = max(0, min(100, new_fuel_level))
            
            self.session.commit()
            return ambulance.fuel_level
        return None

# =============================================================================
# AUTHENTICATION (UNCHANGED)
# =============================================================================
class Authentication:
    def __init__(self):
        self.credentials = {
            'usernames': {
                'admin': {
                    'password': self._hash_password('admin123'),
                    'email': 'admin@kisumu.gov',
                    'role': 'Admin',
                    'hospital': 'All Facilities',
                    'name': 'System Administrator'
                },
                'hospital_staff': {
                    'password': self._hash_password('staff123'),
                    'email': 'staff@joortrh.go.ke',
                    'role': 'Hospital Staff',
                    'hospital': 'Jaramogi Oginga Odinga Teaching & Referral Hospital (JOOTRH)',
                    'name': 'Hospital Staff Member'
                },
                'driver': {
                    'password': self._hash_password('driver123'),
                    'email': 'driver@kisumu.gov',
                    'role': 'Ambulance Driver',
                    'hospital': 'Ambulance Service',
                    'name': 'Ambulance Driver'
                },
                'kisumu_staff': {
                    'password': self._hash_password('kisumu123'),
                    'email': 'staff@kisumuhospital.go.ke',
                    'role': 'Hospital Staff',
                    'hospital': 'Kisumu County Referral Hospital',
                    'name': 'Kisumu County Hospital Staff'
                }
            }
        }
    
    def _hash_password(self, password):
        return hashlib.sha256(password.encode()).hexdigest()
    
    def authenticate_user(self, username, password):
        if username in self.credentials['usernames']:
            stored_password = self.credentials['usernames'][username]['password']
            if self._hash_password(password) == stored_password:
                return self.credentials['usernames'][username]
        return None
    
    def setup_auth_ui(self):
        st.sidebar.title("🔐 Login")
        username = st.sidebar.text_input("Username")
        password = st.sidebar.text_input("Password", type="password")
        
        if st.sidebar.button("Login", use_container_width=True):
            user = self.authenticate_user(username, password)
            if user:
                st.session_state.user = user
                st.session_state.authenticated = True
                st.sidebar.success(f"Welcome {user['role']}!")
                st.rerun()
            else:
                st.sidebar.error("Invalid credentials")
        
        if st.session_state.get('authenticated'):
            if st.sidebar.button("Logout", use_container_width=True):
                st.session_state.clear()
                st.rerun()
    
    def require_auth(self, roles=None):
        if not st.session_state.get('authenticated'):
            st.warning("Please login to access this page")
            return False
        if roles and st.session_state.user['role'] not in roles:
            st.error(f"Access denied. Required roles: {', '.join(roles)}")
            return False
        return True

# =============================================================================
# NEW COST CALCULATION SERVICE
# =============================================================================
class CostCalculationService:
    def __init__(self, db):
        self.db = db
    
    def calculate_trip_cost(self, distance_km, fuel_consumption_rate=None):
        """Calculate cost for a trip based on distance"""
        if fuel_consumption_rate is None:
            fuel_consumption_rate = Config.AVERAGE_FUEL_CONSUMPTION
        
        fuel_used = distance_km * fuel_consumption_rate
        fuel_cost = fuel_used * Config.FUEL_PRICE_PER_LITER
        operating_cost = distance_km * Config.BASE_OPERATING_COST_PER_KM
        total_cost = fuel_cost + operating_cost
        
        return {
            'distance_km': distance_km,
            'fuel_used_liters': fuel_used,
            'fuel_cost_ksh': fuel_cost,
            'operating_cost_ksh': operating_cost,
            'total_cost_ksh': total_cost
        }
    
    def calculate_potential_savings(self, actual_distance, alternative_distance):
        """Calculate potential savings from efficient routing"""
        actual_cost = self.calculate_trip_cost(actual_distance)
        alternative_cost = self.calculate_trip_cost(alternative_distance)
        
        savings = alternative_cost['total_cost_ksh'] - actual_cost['total_cost_ksh']
        return max(0, savings)
    
    def update_ambulance_costs(self, ambulance_id, distance_km):
        """Update ambulance cost tracking after a trip"""
        ambulance = self.db.session.query(Ambulance).filter(
            Ambulance.ambulance_id == ambulance_id
        ).first()
        
        if ambulance:
            trip_cost = self.calculate_trip_cost(distance_km, ambulance.fuel_consumption_rate)
            
            ambulance.total_distance_traveled += distance_km
            ambulance.total_fuel_cost += trip_cost['fuel_cost_ksh']
            
            potential_savings = trip_cost['total_cost_ksh'] * 0.15
            ambulance.cost_savings += potential_savings
            
            self.db.session.commit()
            return trip_cost
        
        return None

# =============================================================================
# ENHANCED NOTIFICATION SERVICE WITH AUTOMATIC MESSAGES
# =============================================================================
class NotificationService:
    def __init__(self, db):
        self.db = db
    
    def send_sms(self, to_number, message):
        st.warning("SMS notifications not configured (Twilio not available)")
        return False
    
    def send_email(self, to_email, subject, message):
        try:
            smtp_server = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
            smtp_port = int(os.getenv('SMTP_PORT', 587))
            smtp_username = os.getenv('SMTP_USERNAME')
            smtp_password = os.getenv('SMTP_PASSWORD')
            
            if not smtp_username or not smtp_password:
                st.warning("Email configuration not complete")
                return False
                
            msg = MIMEMultipart()
            msg['From'] = smtp_username
            msg['To'] = to_email
            msg['Subject'] = subject
            msg.attach(MIMEText(message, 'plain'))
            
            server = smtplib.SMTP(smtp_server, smtp_port)
            server.starttls()
            server.login(smtp_username, smtp_password)
            server.send_message(msg)
            server.quit()
            return True
        except Exception as e:
            st.error(f"Failed to send email: {e}")
            return False
    
    def send_notification(self, recipient, message, notification_type):
        if notification_type == 'referral':
            subject = "New Patient Referral"
        elif notification_type == 'dispatch':
            subject = "Ambulance Dispatched"
        elif notification_type == 'arrival':
            subject = "Patient Arrival Notification"
        elif notification_type == 'pickup':
            subject = "Patient Picked Up - Ambulance En Route"
        else:
            subject = "Hospital Referral System Notification"
        
        st.success(f"📧 Notification prepared: {subject} - {message}")
        return True
    
    # ENHANCED: Automatic notification methods
    def send_automatic_pickup_notification_to_driver(self, patient, ambulance):
        """Send automatic notification to driver when assigned to a referral"""
        message = f"""
🚑 NEW PATIENT PICKUP ASSIGNMENT

Patient: {patient.name}
Age: {patient.age}
Condition: {patient.condition}
Location: {patient.referring_hospital}
Destination: {patient.receiving_hospital}
Referring Physician: {patient.referring_physician}

Clinical Notes: {patient.notes or 'None'}
Medical History: {patient.medical_history or 'None'}
Allergies: {patient.allergies or 'None'}

Please proceed to {patient.referring_hospital} immediately for patient pickup.

Estimated Distance: {patient.trip_distance or 'Calculating...'} km
Priority: HIGH

Reply to this message with your ETA or any issues.
        """.strip()
        
        comm_data = {
            'patient_id': patient.patient_id,
            'ambulance_id': ambulance.ambulance_id,
            'sender': 'System',
            'receiver': ambulance.driver_name,
            'message': message,
            'message_type': 'auto_driver_assignment'
        }
        self.db.add_communication(comm_data)
        
        if ambulance.driver_contact:
            st.success(f"📱 Automatic notification sent to driver {ambulance.driver_name} at {ambulance.driver_contact}")
        
        return True
    
    def send_automatic_referral_notification_to_hospital(self, patient, ambulance=None):
        """Send automatic notification to receiving hospital when referral is created"""
        ambulance_info = ""
        if ambulance:
            ambulance_info = f"\nAssigned Ambulance: {ambulance.ambulance_id} - {ambulance.driver_name}"
            if ambulance.driver_contact:
                ambulance_info += f" ({ambulance.driver_contact})"
        
        message = f"""
🏥 NEW PATIENT REFERRAL INCOMING

Patient: {patient.name}
Age: {patient.age}
Condition: {patient.condition}
Referring Hospital: {patient.referring_hospital}
Referring Physician: {patient.referring_physician}
Receiving Physician: {patient.receiving_physician or 'To be assigned'}

Clinical Notes: {patient.notes or 'None'}
Medical History: {patient.medical_history or 'None'}
Current Medications: {patient.current_medications or 'None'}
Allergies: {patient.allergies or 'None'}
{ambulance_info}

Expected arrival: Within 30-45 minutes
Status: Ambulance Dispatch Initiated

Please prepare for patient arrival and assign receiving physician.
        """.strip()
        
        comm_data = {
            'patient_id': patient.patient_id,
            'ambulance_id': ambulance.ambulance_id if ambulance else None,
            'sender': 'System',
            'receiver': patient.receiving_hospital,
            'message': message,
            'message_type': 'auto_hospital_notification'
        }
        self.db.add_communication(comm_data)
        
        st.success(f"🏥 Automatic referral notification sent to {patient.receiving_hospital}")
        return True
    
    def send_automatic_enroute_notification(self, patient, ambulance):
        """Send automatic enroute notification to receiving hospital when patient is picked up"""
        message = f"""
🚑 PATIENT PICKED UP - AMBULANCE EN ROUTE

Patient: {patient.name}
Ambulance: {ambulance.ambulance_id}
Driver: {ambulance.driver_name}
Current Location: {ambulance.current_location or 'En route'}
Estimated Arrival: 15-25 minutes

Patient Condition: {patient.condition}
Vital Signs: {patient.vital_signs or 'Stable during transport'}

Please ensure receiving team is ready at emergency entrance.
        """.strip()
        
        comm_data = {
            'patient_id': patient.patient_id,
            'ambulance_id': ambulance.ambulance_id,
            'sender': 'System',
            'receiver': patient.receiving_hospital,
            'message': message,
            'message_type': 'auto_enroute_notification'
        }
        self.db.add_communication(comm_data)
        
        st.success(f"📍 Automatic enroute notification sent to {patient.receiving_hospital}")
        return True
    
    def send_automatic_arrival_notification(self, patient, ambulance):
        """Send automatic arrival notification when patient arrives at destination"""
        message = f"""
✅ PATIENT ARRIVED AT DESTINATION

Patient: {patient.name} has arrived at {patient.receiving_hospital}
Ambulance: {ambulance.ambulance_id}
Arrival Time: {datetime.now().strftime('%Y-%m-%d %H:%M')}
Trip Distance: {patient.trip_distance or 'Unknown'} km
Fuel Used: {(patient.trip_distance * ambulance.fuel_consumption_rate) if patient.trip_distance else 'Unknown'} L

Patient handed over to receiving team.
Ambulance status: Returning to service
        """.strip()
        
        hospitals = [patient.referring_hospital, patient.receiving_hospital]
        for hospital in hospitals:
            comm_data = {
                'patient_id': patient.patient_id,
                'ambulance_id': ambulance.ambulance_id,
                'sender': 'System',
                'receiver': hospital,
                'message': message,
                'message_type': 'auto_arrival_notification'
            }
            self.db.add_communication(comm_data)
        
        st.success(f"✅ Automatic arrival notifications sent to both hospitals")
        return True

# =============================================================================
# ENHANCED ANALYTICS SERVICE WITH COST TRACKING
# =============================================================================
class AnalyticsService:
    def __init__(self, db):
        self.db = db
        self.cost_service = CostCalculationService(db)
    
    def get_kpis(self):
        patients = self.db.get_all_patients()
        ambulances = self.db.get_all_ambulances()
        total_referrals = len(patients)
        active_referrals = len([p for p in patients if p.status not in ['Arrived at Destination', 'Completed']])
        available_ambulances = len([a for a in ambulances if a.status == 'Available'])
        response_times = []
        
        # Calculate cost-related KPIs
        total_fuel_cost = sum(amb.total_fuel_cost for amb in ambulances)
        total_cost_savings = sum(amb.cost_savings for amb in ambulances)
        total_distance = sum(amb.total_distance_traveled for amb in ambulances)
        
        for patient in patients:
            if patient.assigned_ambulance and patient.status == 'Arrived at Destination':
                response_times.append(15)
        
        avg_response_time = sum(response_times) / len(response_times) if response_times else 0
        
        return {
            'total_referrals': total_referrals,
            'active_referrals': active_referrals,
            'available_ambulances': available_ambulances,
            'avg_response_time': f"{avg_response_time:.1f} min",
            'completion_rate': f"{(total_referrals - active_referrals) / total_referrals * 100:.1f}%" if total_referrals > 0 else "0%",
            'total_fuel_cost': total_fuel_cost,
            'total_cost_savings': total_cost_savings,
            'total_distance_km': total_distance,
            'fuel_efficiency': f"{(total_distance / (sum(amb.fuel_consumption_rate for amb in ambulances) * total_distance) * 100):.1f}%" if total_distance > 0 else "0%"
        }
    
    def get_referral_trends(self):
        patients = self.db.get_all_patients()
        df = pd.DataFrame([{
            'date': p.referral_time.date(),
            'condition': p.condition,
            'hospital': p.referring_hospital
        } for p in patients])
        if not df.empty:
            trends = df.groupby('date').size().reset_index(name='count')
            return trends
        return pd.DataFrame()
    
    def get_hospital_stats(self):
        patients = self.db.get_all_patients()
        df = pd.DataFrame([{
            'hospital': p.referring_hospital,
            'status': p.status
        } for p in patients])
        if not df.empty:
            stats = df.groupby(['hospital', 'status']).size().reset_index(name='count')
            return stats
        return pd.DataFrame()
    
    def get_cost_analytics(self):
        """Get detailed cost analytics"""
        ambulances = self.db.get_all_ambulances()
        patients = self.db.get_all_patients()
        
        completed_trips = [p for p in patients if p.status == 'Completed']
        total_trip_costs = sum(p.trip_fuel_cost or 0 for p in completed_trips)
        total_trip_savings = sum(p.trip_cost_savings or 0 for p in completed_trips)
        
        # Monthly trend (simulated)
        months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun']
        monthly_costs = [total_trip_costs * (0.8 + i * 0.1) for i in range(6)]
        monthly_savings = [total_trip_savings * (0.7 + i * 0.15) for i in range(6)]
        
        return {
            'monthly_costs': monthly_costs,
            'monthly_savings': monthly_savings,
            'months': months,
            'total_trip_costs': total_trip_costs,
            'total_trip_savings': total_trip_savings,
            'ambulance_count': len(ambulances)
        }

# =============================================================================
# ENHANCED REFERRAL SERVICE WITH COST TRACKING & AUTOMATIC NOTIFICATIONS
# =============================================================================
class ReferralService:
    def __init__(self, db, notification_service):
        self.db = db
        self.notification_service = notification_service
        self.cost_service = CostCalculationService(db)
    
    def create_referral(self, patient_data, user):
        try:
            patient_data['created_by'] = user['role']
            
            # Calculate estimated distance and cost
            if (patient_data.get('referring_hospital_lat') and 
                patient_data.get('referring_hospital_lng') and
                patient_data.get('receiving_hospital_lat') and 
                patient_data.get('receiving_hospital_lng')):
                
                distance = self.db.calculate_distance(
                    patient_data['referring_hospital_lat'],
                    patient_data['referring_hospital_lng'],
                    patient_data['receiving_hospital_lat'],
                    patient_data['receiving_hospital_lng']
                )
                
                cost_estimate = self.cost_service.calculate_trip_cost(distance)
                patient_data['trip_distance'] = distance
                patient_data['trip_fuel_cost'] = cost_estimate['total_cost_ksh']
            
            patient = self.db.add_patient(patient_data)
            referral_data = {
                'patient_id': patient.patient_id,
                'ambulance_id': patient_data.get('assigned_ambulance'),
                'created_by': user['role']
            }
            self.db.add_referral(referral_data)
            
            # Send automatic notification to receiving hospital
            self.notification_service.send_automatic_referral_notification_to_hospital(patient)
            
            return patient
        except Exception as e:
            st.error(f"Error creating referral: {e}")
            return None
    
    def assign_ambulance(self, patient_id, ambulance_id):
        try:
            patient = self.db.get_patient_by_id(patient_id)
            if patient:
                patient.assigned_ambulance = ambulance_id
                patient.status = 'Ambulance Assigned'
                self.db.session.commit()
                
                ambulance = self.db.session.query(Ambulance).filter(
                    Ambulance.ambulance_id == ambulance_id
                ).first()
                
                # Send automatic notification to driver
                if ambulance:
                    self.notification_service.send_automatic_pickup_notification_to_driver(patient, ambulance)
                
                self.db.update_ambulance_status(ambulance_id, 'On Transfer', patient_id)
                return True
        except Exception as e:
            st.error(f"Error assigning ambulance: {e}")
        return False
    
    def auto_assign_nearest_ambulance(self, patient_id):
        patient = self.db.get_patient_by_id(patient_id)
        if not patient or not patient.referring_hospital_lat or not patient.referring_hospital_lng:
            st.error("Patient or hospital location data missing")
            return False
        
        nearest_ambulance = self.db.find_nearest_ambulance(
            patient.referring_hospital_lat, 
            patient.referring_hospital_lng
        )
        
        if not nearest_ambulance:
            st.error("No available ambulances with sufficient fuel")
            return False
        
        patient.assigned_ambulance = nearest_ambulance.ambulance_id
        patient.status = 'Ambulance Assigned'
        
        nearest_ambulance.status = 'On Transfer'
        nearest_ambulance.current_patient = patient_id
        nearest_ambulance.destination = patient.receiving_hospital
        
        # Send automatic notifications
        self.notification_service.send_automatic_pickup_notification_to_driver(patient, nearest_ambulance)
        
        self.db.session.commit()
        st.success(f"🚑 Nearest ambulance {nearest_ambulance.ambulance_id} assigned to patient {patient.name}")
        return True
    
    def mark_patient_picked_up(self, patient_id):
        patient = self.db.get_patient_by_id(patient_id)
        if not patient:
            st.error("Patient not found")
            return False
        
        ambulance = self.db.session.query(Ambulance).filter(
            Ambulance.ambulance_id == patient.assigned_ambulance
        ).first()
        
        if not ambulance:
            st.error("Assigned ambulance not found")
            return False
        
        patient.status = 'Patient Picked Up'
        patient.pickup_notification_sent = True
        
        # Send automatic enroute notification to receiving hospital
        self.notification_service.send_automatic_enroute_notification(patient, ambulance)
        
        self.db.session.commit()
        st.success(f"✅ Patient {patient.name} marked as picked up. Receiving hospital notified.")
        return True
    
    def complete_mission(self, ambulance, patient):
        """Enhanced complete mission with cost tracking and automatic notifications"""
        ambulance.status = 'Available'
        ambulance.current_patient = None
        ambulance.mission_complete = True
        patient.status = 'Arrived at Destination'
        
        # Calculate and update costs
        if patient.trip_distance:
            trip_cost = self.cost_service.update_ambulance_costs(
                ambulance.ambulance_id, 
                patient.trip_distance
            )
            
            if trip_cost:
                patient.trip_fuel_cost = trip_cost['total_cost_ksh']
                patient.trip_cost_savings = trip_cost['total_cost_ksh'] * 0.15
        
        self.db.session.commit()
        
        # Send automatic arrival notification
        self.notification_service.send_automatic_arrival_notification(patient, ambulance)
        
        st.success("Mission completed! Patient delivered successfully.")
        st.balloons()

class AmbulanceService:
    def __init__(self, db):
        self.db = db
    
    def get_available_ambulances_df(self):
        ambulances = self.db.get_available_ambulances()
        data = []
        for ambulance in ambulances:
            data.append({
                'Ambulance ID': ambulance.ambulance_id,
                'Driver': ambulance.driver_name,
                'Contact': ambulance.driver_contact,
                'Location': ambulance.current_location,
                'Status': ambulance.status,
                'Fuel Level': f"{ambulance.fuel_level:.1f}%",
                'Cost Efficiency': f"{(ambulance.cost_savings / ambulance.total_fuel_cost * 100) if ambulance.total_fuel_cost > 0 else 0:.1f}%"
            })
        return pd.DataFrame(data)
    
    def update_ambulance_location(self, ambulance_id, latitude, longitude, location_name, patient_id=None):
        try:
            ambulance = self.db.session.query(Ambulance).filter(
                Ambulance.ambulance_id == ambulance_id
            ).first()
            if ambulance:
                ambulance.latitude = latitude
                ambulance.longitude = longitude
                ambulance.current_location = location_name
                ambulance.last_location_update = datetime.utcnow()
                self.db.session.commit()
                
                location_data = {
                    'ambulance_id': ambulance_id,
                    'latitude': latitude,
                    'longitude': longitude,
                    'location_name': location_name,
                    'patient_id': patient_id
                }
                self.db.add_location_update(location_data)
                return True
        except Exception as e:
            st.error(f"Error updating ambulance location: {e}")
        return False
    
    def get_ambulance_with_fuel_info(self, ambulance_id):
        ambulance = self.db.session.query(Ambulance).filter(
            Ambulance.ambulance_id == ambulance_id
        ).first()
        
        if ambulance:
            fuel_status = "🟢 Good" if ambulance.fuel_level > 50 else "🟡 Low" if ambulance.fuel_level > 20 else "🔴 Critical"
            return {
                'ambulance': ambulance,
                'fuel_level': ambulance.fuel_level,
                'fuel_status': fuel_status
            }
        return None

class LocationSimulator:
    def __init__(self, db):
        self.db = db
        self.running = False
    
    def start_simulation(self, ambulance_id, patient_id, start_lat, start_lng, end_lat, end_lng):
        self.running = True
        ambulance_service = AmbulanceService(self.db)
        
        initial_distance = self.db.calculate_distance(start_lat, start_lng, end_lat, end_lng)
        
        current_lat, current_lng = start_lat, start_lng
        steps = 20
        lat_step = (end_lat - start_lat) / steps
        lng_step = (end_lng - start_lng) / steps
        
        for step in range(steps + 1):
            if not self.running:
                break
                
            current_lat = start_lat + (lat_step * step)
            current_lng = start_lng + (lng_step * step)
            
            ambulance_service.update_ambulance_location(
                ambulance_id, current_lat, current_lng, 
                f"En route - Step {step}/{steps}", patient_id
            )
            
            if step > 0:
                distance_step = initial_distance / steps
                self.db.update_ambulance_fuel(ambulance_id, distance_step)
            
            time.sleep(5)
        
        if self.running:
            ambulance = self.db.session.query(Ambulance).filter(
                Ambulance.ambulance_id == ambulance_id
            ).first()
            if ambulance:
                ambulance.status = 'Available'
                ambulance.current_patient = None
                self.db.session.commit()
    
    def stop_simulation(self):
        self.running = False

# =============================================================================
# UTILITIES - ENHANCED WITH COST DISPLAY
# =============================================================================
class MapUtils:
    @staticmethod
    def create_uber_style_map(patient, ambulance, hospitals_df):
        if not ambulance or not patient:
            return None
        
        referring_hospital_data = hospitals_df[hospitals_df['facility_name'] == patient.referring_hospital].iloc[0]
        receiving_hospital_data = hospitals_df[hospitals_df['facility_name'] == patient.receiving_hospital].iloc[0]
        
        hospitals_layer = pdk.Layer(
            'ScatterplotLayer',
            data=[
                {
                    'name': patient.referring_hospital,
                    'coordinates': [referring_hospital_data['longitude'], referring_hospital_data['latitude']],
                    'color': [0, 128, 0, 200],
                    'radius': 300
                },
                {
                    'name': patient.receiving_hospital,
                    'coordinates': [receiving_hospital_data['longitude'], receiving_hospital_data['latitude']],
                    'color': [255, 0, 0, 200],
                    'radius': 300
                }
            ],
            get_position='coordinates',
            get_color='color',
            get_radius='radius',
            pickable=True
        )
        
        ambulance_layer = pdk.Layer(
            'ScatterplotLayer',
            data=[{
                'name': f"Ambulance {ambulance.ambulance_id} - Fuel: {ambulance.fuel_level:.1f}%",
                'coordinates': [ambulance.longitude, ambulance.latitude],
                'color': [0, 0, 255, 200],
                'radius': 200
            }],
            get_position='coordinates',
            get_color='color',
            get_radius='radius',
            pickable=True
        )
        
        route_layer = pdk.Layer(
            'LineLayer',
            data=[{
                'path': [
                    [referring_hospital_data['longitude'], referring_hospital_data['latitude']],
                    [ambulance.longitude, ambulance.latitude],
                    [receiving_hospital_data['longitude'], receiving_hospital_data['latitude']]
                ],
                'color': [255, 165, 0, 150]
            }],
            get_path='path',
            get_color='color',
            get_width=5,
            pickable=True
        )
        
        center_lat = (referring_hospital_data['latitude'] + receiving_hospital_data['latitude'] + ambulance.latitude) / 3
        center_lng = (referring_hospital_data['longitude'] + receiving_hospital_data['longitude'] + ambulance.longitude) / 3
        
        view_state = pdk.ViewState(
            latitude=center_lat,
            longitude=center_lng,
            zoom=11,
            pitch=0
        )
        
        return pdk.Deck(
            layers=[hospitals_layer, ambulance_layer, route_layer],
            initial_view_state=view_state,
            tooltip={
                'html': '<b>{name}</b>',
                'style': {'color': 'white'}
            }
        )

    @staticmethod
    def embed_google_maps(latitude, longitude, zoom=12):
        if Config.GOOGLE_MAPS_API_KEY:
            return f"""
            <iframe
                width="100%"
                height="400"
                frameborder="0" style="border:0"
                src="https://www.google.com/maps/embed/v1/view?key={Config.GOOGLE_MAPS_API_KEY}&center={latitude},{longitude}&zoom={zoom}"
                allowfullscreen>
            </iframe>
            """
        else:
            return """
            <div style="background-color: #f0f0f0; padding: 20px; text-align: center;">
                <h3>Google Maps Integration</h3>
                <p>To enable Google Maps, please set the GOOGLE_MAPS_API_KEY environment variable.</p>
                <p>Current coordinates: {latitude}, {longitude}</p>
            </div>
            """
    
    @staticmethod
    def create_real_time_tracking_map(patient, ambulance, hospitals_df):
        if not ambulance or not patient:
            st.info("Waiting for ambulance assignment...")
            return
        
        referring_hospital_data = hospitals_df[hospitals_df['facility_name'] == patient.referring_hospital].iloc[0]
        receiving_hospital_data = hospitals_df[hospitals_df['facility_name'] == patient.receiving_hospital].iloc[0]
        
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Ambulance", ambulance.ambulance_id)
        with col2:
            st.metric("Driver", ambulance.driver_name)
        with col3:
            fuel_status = "🟢 Good" if ambulance.fuel_level > 50 else "🟡 Low" if ambulance.fuel_level > 20 else "🔴 Critical"
            st.metric("Fuel Level", f"{ambulance.fuel_level:.1f}%", fuel_status)
        with col4:
            st.metric("Status", ambulance.status)
        
        # Display cost information if available
        if patient.trip_distance:
            cost_service = CostCalculationService(None)
            cost_estimate = cost_service.calculate_trip_cost(patient.trip_distance)
            
            st.subheader("💰 Trip Cost Analysis")
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Distance", f"{patient.trip_distance:.1f} km")
            with col2:
                st.metric("Fuel Cost", f"KSh {cost_estimate['fuel_cost_ksh']:,.0f}")
            with col3:
                st.metric("Total Cost", f"KSh {cost_estimate['total_cost_ksh']:,.0f}")
            with col4:
                potential_savings = cost_estimate['total_cost_ksh'] * 0.15
                st.metric("Potential Savings", f"KSh {potential_savings:,.0f}")
        
        if Config.GOOGLE_MAPS_API_KEY and ambulance.latitude and ambulance.longitude:
            st.subheader("📍 Live Ambulance Tracking on Google Maps")
            
            map_html = f"""
            <iframe
                width="100%"
                height="500"
                frameborder="0" style="border:0"
                src="https://www.google.com/maps/embed/v1/view?key={Config.GOOGLE_MAPS_API_KEY}&center={ambulance.latitude},{ambulance.longitude}&zoom=13&maptype=roadmap"
                allowfullscreen>
            </iframe>
            """
            st.components.v1.html(map_html, height=520)
            
            st.subheader("Route Information")
            col1, col2 = st.columns(2)
            with col1:
                st.write(f"**From:** {patient.referring_hospital}")
                st.write(f"**To:** {patient.receiving_hospital}")
                st.write(f"**Current Location:** {ambulance.current_location or 'Unknown'}")
            with col2:
                if ambulance.last_location_update:
                    time_diff = datetime.utcnow() - ambulance.last_location_update
                    st.write(f"**Last Update:** {time_diff.seconds // 60} minutes ago")
                st.write(f"**Patient:** {patient.name}")
                st.write(f"**Condition:** {patient.condition}")
        else:
            st.subheader("📍 Live Ambulance Tracking")
            map_obj = MapUtils.create_uber_style_map(patient, ambulance, hospitals_df)
            if map_obj:
                st.pydeck_chart(map_obj)

class PDFExporter:
    def __init__(self):
        self.styles = getSampleStyleSheet()
    
    def export_referral_form(self, patient, ambulance, output_path):
        doc = SimpleDocTemplate(output_path, pagesize=A4)
        story = []
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=self.styles['Heading1'],
            fontSize=16,
            spaceAfter=30,
            alignment=1
        )
        story.append(Paragraph("HOSPITAL PATIENT REFERRAL FORM", title_style))
        story.append(Spacer(1, 20))
        patient_data = [
            ['Patient Information', ''],
            ['Patient ID:', patient.patient_id],
            ['Name:', patient.name],
            ['Age:', str(patient.age)],
            ['Condition:', patient.condition],
            ['Referring Physician:', patient.referring_physician]
        ]
        patient_table = Table(patient_data, colWidths=[2*inch, 4*inch])
        patient_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        story.append(patient_table)
        story.append(Spacer(1, 20))
        doc.build(story)
        return output_path

class SecurityUtils:
    @staticmethod
    def generate_secure_password(length=12):
        alphabet = string.ascii_letters + string.digits + string.punctuation
        password = ''.join(secrets.choice(alphabet) for _ in range(length))
        return password
    
    @staticmethod
    def hash_password(password):
        return hashlib.sha256(password.encode()).hexdigest()
    
    @staticmethod
    def verify_password(password, hashed):
        return SecurityUtils.hash_password(password) == hashed

# =============================================================================
# DATA MODELS - UPDATED WITH COST INFORMATION
# =============================================================================
hospitals_data = {
    'facility_name': [
        'Jaramogi Oginga Odinga Teaching & Referral Hospital (JOOTRH)',
        'Kisumu County Referral Hospital', 'Lumumba Sub-County Hospital', 'Ahero Sub-County Hospital',
        'Kombewa Sub-County / District Hospital', 'Muhoroni County Hospital', 'Nyakach Sub-County Hospital',
        'Chulaimbo Sub-County Hospital', 'Masogo Sub-County (Sub-District) Hospital', 'Nyando District Hospital',
        'Ober Kamoth Sub-County Hospital', 'Rabuor Sub-County Hospital', 'Nyangoma Sub-County Hospital',
        'Nyahera Sub-County Hospital', 'Katito Sub-County Hospital', 'Gita Sub-County Hospital',
        'Masogo Health Centre', 'Victoria Hospital (public) Kisumu', 'Kodiaga Prison Health Centre',
        'Kisumu District Hospital', 'Migosi Health Centre', 'Katito Health Centre', 'Mbaka Oromo Health Centre',
        'Migere Health Centre', 'Milenye Health Centre', 'Minyange Dispensary', 'Nduru Kadero Health Centre',
        'Newa Dispensary', 'Nyakoko Dispensary', 'Ojola Sub-County Hospital', 'Simba Opepo Health Centre',
        'Songhor Health Centre', 'St Marks Lela Health Centre', 'Maseno University Health Centre',
        'Geta Health Centre', 'Kadinda Health Centre', 'Kochieng Health Centre', 'Kodingo Health Centre',
        'Kolenyo Health Centre', 'Kandu Health Centre'
    ],
    'latitude': [
        -0.0754, -0.0754, -0.1058, -0.1743, -0.1813, -0.1551, -0.2670, -0.1848, -0.1855, -0.3573,
        -0.3789, -0.2138, -0.1625, -0.1565, -0.4533, -0.3735, -0.1855, -0.0878, -0.0607, -0.0916,
        -0.1073, -0.4533, -0.2628, -0.1225, -0.1872, -0.2192, -0.1356, -0.2014, -0.2678, -0.1578,
        -0.3381, -0.2131, -0.0803, -0.0025, -0.4739, -0.2167, -0.3658, -0.0956, -0.4536, -0.2314
    ],
    'longitude': [
        34.7695, 34.7695, 34.7568, 34.9169, 34.6326, 35.1985, 35.0569, 34.6163, 35.0386, 35.0006,
        35.0299, 34.8817, 34.7794, 34.7508, 34.9561, 34.9676, 35.0386, 34.7686, 34.7509, 34.7647,
        34.7794, 34.9561, 34.6061, 34.7553, 34.7781, 34.8331, 34.7381, 34.8289, 34.9981, 34.8419,
        34.9456, 35.1611, 34.6569, 34.6053, 34.9519, 34.8419, 34.9606, 34.7658, 34.9564, 34.8489
    ],
    'facility_type': [
        'Referral Hospital', 'Referral Hospital', 'Sub-County Hospital', 'Sub-County Hospital',
        'Sub-County Hospital', 'County Hospital', 'Sub-County Hospital', 'Sub-County Hospital',
        'Sub-County Hospital', 'District Hospital', 'Sub-County Hospital', 'Sub-County Hospital',
        'Sub-County Hospital', 'Sub-County Hospital', 'Sub-County Hospital', 'Sub-County Hospital',
        'Health Centre', 'Private Hospital', 'Prison Health Centre', 'District Hospital', 'Health Centre',
        'Health Centre', 'Health Centre', 'Health Centre', 'Health Centre', 'Dispensary', 'Health Centre',
        'Dispensary', 'Dispensary', 'Sub-County Hospital', 'Health Centre', 'Health Centre', 'Health Centre',
        'University Health Centre', 'Health Centre', 'Health Centre', 'Health Centre', 'Health Centre',
        'Health Centre', 'Health Centre'
    ],
    'capacity': [
        500, 400, 100, 100, 100, 75, 75, 78, 77, 80, 70, 60, 65, 50, 52, 40, 42, 30, 35, 20, 20, 25, 15, 24, 15, 10, 19, 5, 19, 10, 5, 15, 17, 16, 45, 30, 29, 55, 30, 30
    ],
    'ambulance_services': [
        'Available', 'Available', 'Limited', 'Limited', 'Limited', 'Limited', 'Limited', 'Limited',
        'Limited', 'Limited', 'Limited', 'Limited', 'Limited', 'Limited', 'Limited', 'Limited',
        'Limited', 'Limited', 'Limited', 'Limited', 'Limited', 'Limited', 'Limited', 'Limited',
        'Limited', 'Limited', 'Limited', 'Limited', 'Limited', 'Limited', 'Limited', 'Limited',
        'Limited', 'Limited', 'Limited', 'Limited', 'Limited', 'Limited', 'Limited', 'Limited'
    ],
    'contact_number': [
        '+254-57-2055000', '+254-57-2021578', '+254-57-2023456', '+254-57-2034567', '+254-57-2045678',
        '+254-57-2056789', '+254-57-2067890', '+254-57-2078901', '+254-57-2089012', '+254-57-2090123',
        '+254-57-2101234', '+254-57-2112345', '+254-57-2123456', '+254-57-2134567', '+254-57-2145678',
        '+254-57-2156789', '+254-57-2167890', '+254-57-2178901', '+254-57-2189012', '+254-57-2190123',
        '+254-57-2201234', '+254-57-2212345', '+254-57-2223456', '+254-57-2234567', '+254-57-2245678',
        '+254-57-2256789', '+254-57-2267890', '+254-57-2278901', '+254-57-2289012', '+254-57-2290123',
        '+254-57-2301234', '+254-57-2312345', '+254-57-2323456', '+254-57-2334567', '+254-57-2345678',
        '+254-57-2356789', '+254-57-2367890', '+254-57-2378901', '+254-57-2389012', '+254-57-2390123'
    ]
}

hospitals_df = pd.DataFrame(hospitals_data)

ambulances_data = {
    'ambulance_id': [
        'KBA 453D', 'KBC 217F', 'KBD 389G', 'KBE 142H', 'KBF 561J', 'KBG 774K', 'KBH 238L', 'KBJ 965M',
        'KBK 482N', 'KBL 751P', 'KBM 312Q', 'KBN 864R', 'KBP 459S', 'KBQ 287T', 'KBR 913U', 'KBS 506V',
        'KBT 678W', 'KBU 134X', 'KBV 925Y', 'KBX 743Z'
    ],
    'current_location': [
        'Jaramogi Oginga Odinga Teaching & Referral Hospital (JOOTRH)',
        'Jaramogi Oginga Odinga Teaching & Referral Hospital (JOOTRH)',
        'Jaramogi Oginga Odinga Teaching & Referral Hospital (JOOTRH)',
        'Jaramogi Oginga Odinga Teaching & Referral Hospital (JOOTRH)',
        'Jaramogi Oginga Odinga Teaching & Referral Hospital (JOOTRH)',
        'Jaramogi Oginga Odinga Teaching & Referral Hospital (JOOTRH)',
        'Jaramogi Oginga Odinga Teaching & Referral Hospital (JOOTRH)',
        'Jaramogi Oginga Odinga Teaching & Referral Hospital (JOOTRH)',
        'Jaramogi Oginga Odinga Teaching & Referral Hospital (JOOTRH)',
        'Jaramogi Oginga Odinga Teaching & Referral Hospital (JOOTRH)',
        'Kisumu County Referral Hospital', 'Kisumu County Referral Hospital', 'Kisumu County Referral Hospital',
        'Kisumu County Referral Hospital', 'Kisumu County Referral Hospital', 'Kisumu County Referral Hospital',
        'Kisumu County Referral Hospital', 'Lumumba Sub-County Hospital', 'Lumumba Sub-County Hospital',
        'Ahero Sub-County Hospital'
    ],
    'latitude': [
        -0.0754, -0.0754, -0.0754, -0.0754, -0.0754, -0.0754, -0.0754, -0.0754, -0.0754, -0.0754,
        -0.0754, -0.0754, -0.0754, -0.0754, -0.0754, -0.0754, -0.0754, -0.1058, -0.1058, -0.1743
    ],
    'longitude': [
        34.7695, 34.7695, 34.7695, 34.7695, 34.7695, 34.7695, 34.7695, 34.7695, 34.7695, 34.7695,
        34.7695, 34.7695, 34.7695, 34.7695, 34.7695, 34.7695, 34.7695, 34.7568, 34.7568, 34.9169
    ],
    'status': [
        'Available', 'Available', 'Available', 'Available', 'Available', 'Available', 'Available', 'Available',
        'Available', 'Available', 'Available', 'Available', 'Available', 'Available', 'Available', 'Available',
        'Available', 'Available', 'Available', 'Available'
    ],
    'driver_name': [
        'John Omondi', 'Mary Achieng', 'Paul Otieno', 'Susan Akinyi', 'David Owino', 'James Okoth',
        'Grace Atieno', 'Peter Onyango', 'Alice Adhiambo', 'Robert Ochieng', 'Sarah Nyongesa',
        'Michael Odhiambo', 'Elizabeth Awuor', 'Daniel Omondi', 'Lucy Anyango', 'Brian Ouma',
        'Patricia Adongo', 'Samuel Owuor', 'Rebecca Aoko', 'Kevin Onyango'
    ],
    'driver_contact': [
        '+254712345678', '+254723456789', '+254734567890', '+254745678901', '+254756789012',
        '+254767890123', '+254778901234', '+254789012345', '+254790123456', '+254701234567',
        '+254712345679', '+254723456780', '+254734567891', '+254745678902', '+254756789013',
        '+254767890124', '+254778901235', '+254789012346', '+254790123457', '+254701234568'
    ],
    'ambulance_type': [
        'Advanced Life Support', 'Basic Life Support', 'Basic Life Support', 'Advanced Life Support',
        'Basic Life Support', 'Basic Life Support', 'Advanced Life Support', 'Basic Life Support',
        'Basic Life Support', 'Advanced Life Support', 'Basic Life Support', 'Basic Life Support',
        'Advanced Life Support', 'Basic Life Support', 'Basic Life Support', 'Advanced Life Support',
        'Basic Life Support', 'Basic Life Support', 'Basic Life Support', 'Advanced Life Support'
    ],
    'equipment': [
        'Defibrillator, Ventilator, Monitor', 'Basic equipment', 'Basic equipment',
        'Defibrillator, Ventilator, Monitor', 'Basic equipment', 'Basic equipment',
        'Defibrillator, Ventilator, Monitor', 'Basic equipment', 'Basic equipment',
        'Defibrillator, Ventilator, Monitor', 'Basic equipment', 'Basic equipment',
        'Defibrillator, Ventilator, Monitor', 'Basic equipment', 'Basic equipment',
        'Defibrillator, Ventilator, Monitor', 'Basic equipment', 'Basic equipment',
        'Basic equipment', 'Defibrillator, Ventilator, Monitor'
    ],
    'fuel_level': [
        85.5, 92.3, 78.9, 65.2, 88.7, 94.1, 71.8, 83.4, 79.6, 86.9,
        90.2, 67.8, 82.5, 75.9, 88.3, 69.7, 91.4, 84.2, 77.5, 80.8
    ]
}

def initialize_sample_data(db):
    existing_ambulances = db.session.query(Ambulance).count()
    if existing_ambulances == 0:
        for amb_data in ambulances_data['ambulance_id']:
            idx = ambulances_data['ambulance_id'].index(amb_data)
            ambulance = Ambulance(
                ambulance_id=amb_data,
                current_location=ambulances_data['current_location'][idx],
                latitude=ambulances_data['latitude'][idx],
                longitude=ambulances_data['longitude'][idx],
                status=ambulances_data['status'][idx],
                driver_name=ambulances_data['driver_name'][idx],
                driver_contact=ambulances_data['driver_contact'][idx],
                fuel_level=ambulances_data['fuel_level'][idx],
                total_fuel_cost=np.random.uniform(5000, 50000),
                total_distance_traveled=np.random.uniform(100, 1000),
                cost_savings=np.random.uniform(1000, 10000)
            )
            db.session.add(ambulance)
        db.session.commit()

# =============================================================================
# ENHANCED UI COMPONENTS WITH COST TRACKING
# =============================================================================
class DashboardUI:
    def __init__(self, db, analytics):
        self.db = db
        self.analytics = analytics
    
    def display(self):
        st.title("📊 Dashboard Overview")
        
        kpis = self.analytics.get_kpis()
        
        # First row: Basic KPIs
        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            st.metric("Total Referrals", kpis['total_referrals'])
        with col2:
            st.metric("Active Referrals", kpis['active_referrals'])
        with col3:
            st.metric("Available Ambulances", kpis['available_ambulances'])
        with col4:
            st.metric("Avg Response Time", kpis['avg_response_time'])
        with col5:
            st.metric("Completion Rate", kpis['completion_rate'])
        
        # Second row: Cost KPIs
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Fuel Cost", f"KSh {kpis['total_fuel_cost']:,.0f}")
        with col2:
            st.metric("Cost Savings", f"KSh {kpis['total_cost_savings']:,.0f}")
        with col3:
            st.metric("Total Distance", f"{kpis['total_distance_km']:,.1f} km")
        with col4:
            st.metric("Fuel Efficiency", kpis['fuel_efficiency'])
        
        # Charts
        col1, col2 = st.columns(2)
        with col1:
            self.display_cost_analytics()
        with col2:
            self.display_ambulance_cost_breakdown()
        
        st.subheader("Recent Referrals with Cost Analysis")
        self.display_recent_referrals_with_costs()
    
    def display_cost_analytics(self):
        st.subheader("💰 Monthly Cost Analysis")
        cost_data = self.analytics.get_cost_analytics()
        
        fig = px.line(
            x=cost_data['months'],
            y=[cost_data['monthly_costs'], cost_data['monthly_savings']],
            title="Monthly Costs vs Savings",
            labels={'value': 'Amount (KSh)', 'x': 'Month', 'variable': 'Type'}
        )
        fig.data[0].name = 'Costs Incurred'
        fig.data[1].name = 'Costs Saved'
        fig.update_layout(showlegend=True)
        
        st.plotly_chart(fig, use_container_width=True, key="cost_analysis_chart")
        
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Total Trip Costs", f"KSh {cost_data['total_trip_costs']:,.0f}")
        with col2:
            st.metric("Total Trip Savings", f"KSh {cost_data['total_trip_savings']:,.0f}")

    def display_ambulance_cost_breakdown(self):
        st.subheader("🚑 Ambulance Cost Breakdown")
        ambulances = self.db.get_all_ambulances()
        
        if ambulances:
            cost_data = []
            for ambulance in ambulances:
                efficiency = (ambulance.total_distance_traveled / 
                            (ambulance.fuel_consumption_rate * ambulance.total_distance_traveled * 100)) if ambulance.total_distance_traveled > 0 else 0
                
                cost_data.append({
                    'Ambulance': ambulance.ambulance_id,
                    'Fuel Cost (KSh)': ambulance.total_fuel_cost,
                    'Cost Savings (KSh)': ambulance.cost_savings,
                    'Distance (km)': ambulance.total_distance_traveled,
                    'Efficiency': f"{efficiency:.1f}%"
                })
            
            df = pd.DataFrame(cost_data)
            st.dataframe(df, use_container_width=True)
        else:
            st.info("No ambulance cost data available")

    def display_recent_referrals_with_costs(self):
        patients = self.db.get_all_patients()
        recent_patients = sorted(patients, key=lambda x: x.referral_time, reverse=True)[:5]
        
        if recent_patients:
            data = []
            for patient in recent_patients:
                cost_info = ""
                if patient.trip_fuel_cost:
                    cost_info = f"KSh {patient.trip_fuel_cost:,.0f}"
                    if patient.trip_cost_savings:
                        cost_info += f" (Saved: KSh {patient.trip_cost_savings:,.0f})"
                
                data.append({
                    'Patient ID': patient.patient_id,
                    'Name': patient.name,
                    'Condition': patient.condition,
                    'From': patient.referring_hospital,
                    'To': patient.receiving_hospital,
                    'Status': patient.status,
                    'Distance': f"{patient.trip_distance or 0:.1f} km",
                    'Cost': cost_info,
                    'Time': patient.referral_time.strftime('%Y-%m-%d %H:%M')
                })
            
            st.dataframe(pd.DataFrame(data), use_container_width=True)
        else:
            st.info("No recent referrals")

class ReferralUI:
    def __init__(self, db, notification_service):
        self.db = db
        self.notification_service = notification_service
        self.referral_service = ReferralService(db, notification_service)
    
    def display(self):
        st.title("📋 Patient Referral Management")
        tab1, tab2, tab3 = st.tabs(["Create Referral", "Active Referrals", "Referral History"])
        with tab1:
            self.create_referral_form()
        with tab2:
            self.display_active_referrals()
        with tab3:
            self.display_referral_history()
    
    def get_receiving_hospitals(self, user_hospital):
        if user_hospital == "Kisumu County Referral Hospital":
            return [
                "Jaramogi Oginga Odinga Teaching & Referral Hospital (JOOTRH)",
                "Kisumu County Referral Hospital"
            ]
        else:
            return [
                "Jaramogi Oginga Odinga Teaching & Referral Hospital (JOOTRH)",
                "Kisumu County Referral Hospital"
            ]
    
    def get_referring_hospitals(self, user_hospital):
        if user_hospital in ["All Facilities", "Jaramogi Oginga Odinga Teaching & Referral Hospital (JOOTRH)", "Kisumu County Referral Hospital"]:
            return hospitals_data['facility_name']
        else:
            return [user_hospital]
    
    def create_referral_form(self):
        st.subheader("Create New Patient Referral")
        user_hospital = st.session_state.user['hospital']
        
        with st.form("referral_form", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                name = st.text_input("Patient Name*")
                age = st.number_input("Age*", min_value=0, max_value=120, value=30)
                condition = st.text_input("Medical Condition*")
                referring_physician = st.text_input("Referring Physician*")
                
                referring_hospitals = self.get_referring_hospitals(user_hospital)
                referring_hospital = st.selectbox("Referring Hospital*", referring_hospitals)
                
            with col2:
                receiving_hospitals = self.get_receiving_hospitals(user_hospital)
                receiving_hospital = st.selectbox("Receiving Hospital*", receiving_hospitals)
                
                receiving_physician = st.text_input("Receiving Physician")
                
                if referring_hospital == receiving_hospital:
                    st.warning("⚠️ Referring and receiving hospitals cannot be the same.")
                
                if user_hospital not in ["All Facilities", "Jaramogi Oginga Odinga Teaching & Referral Hospital (JOOTRH)", "Kisumu County Referral Hospital"]:
                    st.info("ℹ️ As a referring hospital, you can only refer patients to Jaramogi Oginga Odinga Teaching & Referral Hospital or Kisumu County Referral Hospital.")
                
            notes = st.text_area("Clinical Notes")
            with st.expander("Additional Medical Information"):
                medical_history = st.text_area("Medical History")
                current_medications = st.text_area("Current Medications")
                allergies = st.text_area("Allergies")
            
            st.subheader("🚑 Ambulance Assignment")
            assignment_method = st.radio("Assignment Method", 
                ["Auto-assign nearest ambulance", "Manual selection"], 
                help="Auto-assign will find the nearest available ambulance with sufficient fuel")
            
            if assignment_method == "Manual selection":
                available_ambulances = self.db.get_available_ambulances()
                ambulance_options = ["Select ambulance"] + [f"{amb.ambulance_id} - {amb.driver_name} (Fuel: {amb.fuel_level:.1f}%)" for amb in available_ambulances]
                ambulance_choice = st.selectbox("Select Ambulance", ambulance_options)
            else:
                ambulance_choice = "Auto-assign"
            
            submitted = st.form_submit_button("Create Referral", use_container_width=True)
            if submitted:
                if not all([name, age, condition, referring_physician, referring_hospital, receiving_hospital]):
                    st.error("Please fill in all required fields (*)")
                elif referring_hospital == receiving_hospital:
                    st.error("Referring and receiving hospitals cannot be the same.")
                else:
                    referring_hospital_data = hospitals_df[hospitals_df['facility_name'] == referring_hospital].iloc[0]
                    receiving_hospital_data = hospitals_df[hospitals_df['facility_name'] == receiving_hospital].iloc[0]
                    
                    patient_data = {
                        'name': name, 'age': age, 'condition': condition, 'referring_hospital': referring_hospital,
                        'receiving_hospital': receiving_hospital, 'referring_physician': referring_physician,
                        'receiving_physician': receiving_physician, 'notes': notes, 'medical_history': medical_history,
                        'current_medications': current_medications, 'allergies': allergies, 'status': 'Referred',
                        'referring_hospital_lat': referring_hospital_data['latitude'],
                        'referring_hospital_lng': referring_hospital_data['longitude'],
                        'receiving_hospital_lat': receiving_hospital_data['latitude'],
                        'receiving_hospital_lng': receiving_hospital_data['longitude']
                    }
                    
                    if assignment_method == "Manual selection" and ambulance_choice != "Select ambulance":
                        ambulance_id = ambulance_choice.split(" - ")[0]
                        patient_data['assigned_ambulance'] = ambulance_id
                    
                    patient = self.referral_service.create_referral(patient_data, st.session_state.user)
                    if patient:
                        st.success(f"Referral created successfully! Patient ID: {patient.patient_id}")
                        
                        if assignment_method == "Auto-assign nearest ambulance":
                            if self.referral_service.auto_assign_nearest_ambulance(patient.patient_id):
                                st.success("🚑 Nearest ambulance automatically assigned and driver notified!")
    
    def display_active_referrals(self):
        st.subheader("Active Referrals")
        patients = self.db.get_all_patients()
        user_hospital = st.session_state.user['hospital']
        
        if user_hospital == "All Facilities":
            active_patients = [p for p in patients if p.status not in ['Arrived at Destination', 'Completed']]
        elif user_hospital in ["Jaramogi Oginga Odinga Teaching & Referral Hospital (JOOTRH)", "Kisumu County Referral Hospital"]:
            active_patients = [p for p in patients if p.receiving_hospital == user_hospital and p.status not in ['Arrived at Destination', 'Completed']]
        else:
            active_patients = [p for p in patients if p.referring_hospital == user_hospital and p.status not in ['Arrived at Destination', 'Completed']]
            
        if active_patients:
            data = []
            for patient in active_patients:
                ambulance_info = ""
                if patient.assigned_ambulance:
                    ambulance_service = AmbulanceService(self.db)
                    ambulance_data = ambulance_service.get_ambulance_with_fuel_info(patient.assigned_ambulance)
                    if ambulance_data:
                        ambulance_info = f"{patient.assigned_ambulance} ({ambulance_data['fuel_status']})"
                
                data.append({
                    'Patient ID': patient.patient_id, 'Name': patient.name, 'Condition': patient.condition,
                    'From': patient.referring_hospital, 'To': patient.receiving_hospital,
                    'Status': patient.status, 'Ambulance': ambulance_info or 'Not assigned'
                })
            df = pd.DataFrame(data)
            st.dataframe(df, use_container_width=True)
            
            st.subheader("Patient Actions")
            for patient in active_patients:
                with st.expander(f"Actions for {patient.name} ({patient.patient_id})"):
                    self.display_patient_actions(patient)
        else:
            st.info("No active referrals")
    
    def display_patient_actions(self, patient):
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            if st.button(f"Assign Ambulance", key=f"assign_{patient.patient_id}", use_container_width=True):
                st.session_state[f'assign_ambulance_{patient.patient_id}'] = True
            
            if st.session_state.get(f'assign_ambulance_{patient.patient_id}'):
                available_ambulances = self.db.get_available_ambulances()
                if available_ambulances:
                    ambulance_options = [f"{amb.ambulance_id} - {amb.driver_name} (Fuel: {amb.fuel_level:.1f}%)" for amb in available_ambulances]
                    selected_ambulance = st.selectbox("Select Ambulance", ambulance_options, key=f"amb_select_{patient.patient_id}")
                    if st.button("Confirm Assignment", key=f"confirm_{patient.patient_id}", use_container_width=True):
                        ambulance_id = selected_ambulance.split(" - ")[0]
                        if self.referral_service.assign_ambulance(patient.patient_id, ambulance_id):
                            st.success("Ambulance assigned successfully!")
                            st.session_state[f'assign_ambulance_{patient.patient_id}'] = False
                            st.rerun()
                else:
                    st.warning("No available ambulances")
        
        with col2:
            if st.button("Update Status", key=f"status_{patient.patient_id}", use_container_width=True):
                st.session_state[f'update_status_{patient.patient_id}'] = True
            
            if st.session_state.get(f'update_status_{patient.patient_id}'):
                new_status = st.selectbox("New Status", 
                    ["Referred", "Ambulance Dispatched", "Patient Picked Up", 
                     "Transporting to Destination", "Arrived at Destination"],
                    key=f"status_select_{patient.patient_id}")
                if st.button("Update", key=f"update_{patient.patient_id}", use_container_width=True):
                    patient.status = new_status
                    self.db.session.commit()
                    st.success("Status updated!")
                    st.session_state[f'update_status_{patient.patient_id}'] = False
                    st.rerun()
        
        with col3:
            if st.button("View Details", key=f"details_{patient.patient_id}", use_container_width=True):
                st.session_state[f'view_details_{patient.patient_id}'] = True
            
            if st.session_state.get(f'view_details_{patient.patient_id}'):
                st.write(f"**Medical History:** {patient.medical_history}")
                st.write(f"**Medications:** {patient.current_medications}")
                st.write(f"**Allergies:** {patient.allergies}")
                if st.button("Close", key=f"close_{patient.patient_id}", use_container_width=True):
                    st.session_state[f'view_details_{patient.patient_id}'] = False
                    st.rerun()
        
        with col4:
            if (st.session_state.user['role'] == 'Ambulance Driver' and 
                patient.assigned_ambulance and 
                patient.status == 'Ambulance Dispatched'):
                if st.button("Mark Patient Picked Up", key=f"pickup_{patient.patient_id}", use_container_width=True):
                    if self.referral_service.mark_patient_picked_up(patient.patient_id):
                        st.rerun()
    
    def display_referral_history(self):
        st.subheader("Referral History")
        patients = self.db.get_all_patients()
        user_hospital = st.session_state.user['hospital']
        
        if user_hospital == "All Facilities":
            filtered_patients = patients
        elif user_hospital in ["Jaramogi Oginga Odinga Teaching & Referral Hospital (JOOTRH)", "Kisumu County Referral Hospital"]:
            filtered_patients = [p for p in patients if p.receiving_hospital == user_hospital]
        else:
            filtered_patients = [p for p in patients if p.referring_hospital == user_hospital]
            
        if filtered_patients:
            data = []
            for patient in filtered_patients:
                data.append({
                    'Patient ID': patient.patient_id, 'Name': patient.name, 'Condition': patient.condition,
                    'From': patient.referring_hospital, 'To': patient.receiving_hospital,
                    'Status': patient.status, 'Referral Time': patient.referral_time.strftime('%Y-%m-%d %H:%M'),
                    'Ambulance': patient.assigned_ambulance or 'Not assigned'
                })
            df = pd.DataFrame(data)
            st.dataframe(df, use_container_width=True)
        else:
            st.info("No referral history")

class TrackingUI:
    def __init__(self, db):
        self.db = db
        self.map_utils = MapUtils()
        self.cost_service = CostCalculationService(db)
    
    def display(self):
        st.title("🚑 Live Ambulance Tracking & Cost Management")
        
        col1, col2 = st.columns([3, 1])
        with col2:
            if st.button("🔄 Refresh Data", use_container_width=True):
                st.rerun()
        
        st.markdown("### 🗺️ Real-time Ambulance Tracking with Cost Analysis")
        
        patients = self.db.get_all_patients()
        active_transfers = [p for p in patients if p.status in ['Ambulance Dispatched', 'Patient Picked Up', 'Transporting to Destination']]
        
        if active_transfers:
            for patient in active_transfers:
                with st.expander(f"🚑 {patient.name} - {patient.condition}", expanded=True):
                    ambulance = None
                    if patient.assigned_ambulance:
                        ambulance = self.db.session.query(Ambulance).filter(
                            Ambulance.ambulance_id == patient.assigned_ambulance
                        ).first()
                    
                    if ambulance and patient.trip_distance:
                        col1, col2, col3, col4 = st.columns(4)
                        with col1:
                            estimated_cost = self.cost_service.calculate_trip_cost(patient.trip_distance)
                            st.metric("Estimated Cost", f"KSh {estimated_cost['total_cost_ksh']:,.0f}")
                        with col2:
                            st.metric("Distance", f"{patient.trip_distance:.1f} km")
                        with col3:
                            fuel_used = patient.trip_distance * ambulance.fuel_consumption_rate
                            st.metric("Fuel Needed", f"{fuel_used:.1f} L")
                        with col4:
                            potential_savings = estimated_cost['total_cost_ksh'] * 0.15
                            st.metric("Potential Savings", f"KSh {potential_savings:,.0f}")
                    
                    self.map_utils.create_real_time_tracking_map(patient, ambulance, hospitals_df)
        
        else:
            st.info("No active patient transfers to track")
        
        st.markdown("### 🚑 Ambulance Fleet Cost Analysis")
        self.display_ambulance_cost_list()

    def display_ambulance_cost_list(self):
        ambulances = self.db.get_all_ambulances()
        
        for ambulance in ambulances:
            status_color = "🟢" if ambulance.status == 'Available' else "🔴"
            fuel_indicator = "🟢" if ambulance.fuel_level > 50 else "🟡" if ambulance.fuel_level > 20 else "🔴"
            
            with st.expander(f"{status_color} {ambulance.ambulance_id} - {ambulance.driver_name} {fuel_indicator} Fuel: {ambulance.fuel_level:.1f}%", expanded=False):
                col1, col2 = st.columns(2)
                with col1:
                    st.write(f"**Status:** {ambulance.status}")
                    st.write(f"**Location:** {ambulance.current_location}")
                    st.write(f"**Contact:** {ambulance.driver_contact}")
                    st.write(f"**Total Distance:** {ambulance.total_distance_traveled:,.1f} km")
                
                with col2:
                    st.write(f"**Fuel Level:** {ambulance.fuel_level:.1f}%")
                    st.write(f"**Fuel Cost:** KSh {ambulance.total_fuel_cost:,.0f}")
                    st.write(f"**Cost Savings:** KSh {ambulance.cost_savings:,.0f}")
                    st.write(f"**Efficiency:** {(ambulance.cost_savings / ambulance.total_fuel_cost * 100) if ambulance.total_fuel_cost > 0 else 0:.1f}%")
                
                if ambulance.current_patient:
                    patient = self.db.get_patient_by_id(ambulance.current_patient)
                    if patient:
                        st.write(f"**Current Patient:** {patient.name}")
                        st.write(f"**Destination:** {patient.receiving_hospital}")
                        
                        if patient.trip_distance:
                            cost_info = self.cost_service.calculate_trip_cost(
                                patient.trip_distance, 
                                ambulance.fuel_consumption_rate
                            )
                            st.write(f"**Trip Cost Estimate:** KSh {cost_info['total_cost_ksh']:,.0f}")

# =============================================================================
# NEW COST MANAGEMENT UI
# =============================================================================
class CostManagementUI:
    def __init__(self, db, analytics):
        self.db = db
        self.analytics = analytics
        self.cost_service = CostCalculationService(db)
    
    def display(self):
        st.title("💰 Cost Management & Analytics")
        
        tab1, tab2, tab3, tab4 = st.tabs([
            "Cost Overview", "Fuel Management", "Savings Analysis", "Budget Planning"
        ])
        
        with tab1:
            self.display_cost_overview()
        with tab2:
            self.display_fuel_management()
        with tab3:
            self.display_savings_analysis()
        with tab4:
            self.display_budget_planning()
    
    def display_cost_overview(self):
        st.subheader("📈 Overall Cost Analytics")
        
        kpis = self.analytics.get_kpis()
        cost_data = self.analytics.get_cost_analytics()
        
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Fuel Cost", f"KSh {kpis['total_fuel_cost']:,.0f}")
        with col2:
            st.metric("Total Savings", f"KSh {kpis['total_cost_savings']:,.0f}")
        with col3:
            st.metric("Net Cost", f"KSh {kpis['total_fuel_cost'] - kpis['total_cost_savings']:,.0f}")
        with col4:
            savings_rate = (kpis['total_cost_savings'] / kpis['total_fuel_cost'] * 100) if kpis['total_fuel_cost'] > 0 else 0
            st.metric("Savings Rate", f"{savings_rate:.1f}%")
        
        st.subheader("Cost Distribution")
        ambulances = self.db.get_all_ambulances()
        
        if ambulances:
            cost_distribution = []
            for ambulance in ambulances:
                cost_distribution.append({
                    'Ambulance': ambulance.ambulance_id,
                    'Fuel Cost': ambulance.total_fuel_cost,
                    'Savings': ambulance.cost_savings
                })
            
            df = pd.DataFrame(cost_distribution)
            fig = px.bar(df, x='Ambulance', y=['Fuel Cost', 'Savings'],
                        title="Cost Distribution by Ambulance",
                        barmode='group')
            st.plotly_chart(fig, use_container_width=True)
    
    def display_fuel_management(self):
        st.subheader("⛽ Fuel Management")
        
        ambulances = self.db.get_all_ambulances()
        
        st.subheader("Fuel Price Settings")
        col1, col2 = st.columns(2)
        with col1:
            current_price = st.number_input("Current Fuel Price (KSh/L)", 
                                          value=Config.FUEL_PRICE_PER_LITER, 
                                          min_value=100.0, max_value=300.0)
        with col2:
            if st.button("Update Fuel Price", use_container_width=True):
                Config.FUEL_PRICE_PER_LITER = current_price
                st.success("Fuel price updated!")
        
        st.subheader("Fuel Efficiency Analysis")
        efficiency_data = []
        for ambulance in ambulances:
            if ambulance.total_distance_traveled > 0:
                fuel_used_liters = (ambulance.total_fuel_cost / Config.FUEL_PRICE_PER_LITER)
                efficiency = ambulance.total_distance_traveled / fuel_used_liters if fuel_used_liters > 0 else 0
                
                efficiency_data.append({
                    'Ambulance': ambulance.ambulance_id,
                    'Distance (km)': ambulance.total_distance_traveled,
                    'Fuel Used (L)': fuel_used_liters,
                    'Efficiency (km/L)': efficiency,
                    'Cost per km': ambulance.total_fuel_cost / ambulance.total_distance_traveled
                })
        
        if efficiency_data:
            df = pd.DataFrame(efficiency_data)
            st.dataframe(df, use_container_width=True)
            
            fig = px.bar(df, x='Ambulance', y='Efficiency (km/L)',
                        title="Fuel Efficiency by Ambulance")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No fuel efficiency data available")
    
    def display_savings_analysis(self):
        st.subheader("💵 Savings Analysis")
        
        cost_data = self.analytics.get_cost_analytics()
        
        fig = px.area(x=cost_data['months'], y=cost_data['monthly_savings'],
                     title="Monthly Cost Savings Trend",
                     labels={'x': 'Month', 'y': 'Savings (KSh)'})
        st.plotly_chart(fig, use_container_width=True)
        
        st.subheader("Savings Breakdown")
        ambulances = self.db.get_all_ambulances()
        
        savings_data = []
        for ambulance in ambulances:
            savings_data.append({
                'Ambulance': ambulance.ambulance_id,
                'Savings': ambulance.cost_savings,
                'Savings Rate': (ambulance.cost_savings / ambulance.total_fuel_cost * 100) if ambulance.total_fuel_cost > 0 else 0
            })
        
        if savings_data:
            df = pd.DataFrame(savings_data)
            col1, col2 = st.columns(2)
            with col1:
                st.dataframe(df, use_container_width=True)
            with col2:
                fig = px.pie(df, values='Savings', names='Ambulance',
                            title="Savings Distribution by Ambulance")
                st.plotly_chart(fig, use_container_width=True)
    
    def display_budget_planning(self):
        st.subheader("📊 Budget Planning & Forecasting")
        
        col1, col2 = st.columns(2)
        with col1:
            monthly_budget = st.number_input("Monthly Budget (KSh)", 
                                           value=500000, 
                                           min_value=100000, 
                                           max_value=5000000)
        with col2:
            expected_trips = st.number_input("Expected Monthly Trips", 
                                           value=100, 
                                           min_value=10, 
                                           max_value=1000)
        
        avg_trip_cost = 1500
        projected_cost = expected_trips * avg_trip_cost
        projected_savings = projected_cost * 0.15
        net_projected_cost = projected_cost - projected_savings
        
        st.subheader("Budget Projections")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Projected Cost", f"KSh {projected_cost:,.0f}")
        with col2:
            st.metric("Projected Savings", f"KSh {projected_savings:,.0f}")
        with col3:
            status = "Within Budget" if net_projected_cost <= monthly_budget else "Over Budget"
            st.metric("Budget Status", status, 
                     delta=f"KSh {monthly_budget - net_projected_cost:,.0f}")
        
        budget_data = {
            'Category': ['Projected Cost', 'Projected Savings', 'Net Cost'],
            'Amount': [projected_cost, projected_savings, net_projected_cost]
        }
        df = pd.DataFrame(budget_data)
        fig = px.bar(df, x='Category', y='Amount', 
                    title="Budget Utilization Projection")
        st.plotly_chart(fig, use_container_width=True)

# =============================================================================
# ENHANCED COMMUNICATION UI WITH AUTOMATIC MESSAGES
# =============================================================================
class CommunicationUI:
    def __init__(self, db, notification_service):
        self.db = db
        self.notification_service = notification_service
    
    def display(self):
        st.title("💬 Communication Center")
        tab1, tab2, tab3, tab4 = st.tabs(["All Messages", "Send Message", "Message Templates", "Notification Log"])
        with tab1:
            self.display_all_messages()
        with tab2:
            self.send_custom_message()
        with tab3:
            self.message_templates()
        with tab4:
            self.notification_log()
    
    def display_all_messages(self):
        st.subheader("📨 All Messages & Notifications")
        
        col1, col2, col3 = st.columns(3)
        with col1:
            filter_type = st.selectbox("Filter by Type", 
                ["All Messages", "Automatic Notifications", "Manual Messages", "Driver Messages"])
        with col2:
            filter_status = st.selectbox("Filter by Status", 
                ["All Status", "Unread", "Read"])
        with col3:
            if st.button("🔄 Refresh Messages", use_container_width=True):
                st.rerun()
        
        all_communications = self.db.session.query(Communication).order_by(Communication.timestamp.desc()).all()
        
        if not all_communications:
            st.info("No messages found")
            return
        
        filtered_comms = all_communications
        if filter_type == "Automatic Notifications":
            filtered_comms = [c for c in all_communications if c.sender == 'System']
        elif filter_type == "Manual Messages":
            filtered_comms = [c for c in all_communications if c.sender != 'System' and c.sender != 'Driver']
        elif filter_type == "Driver Messages":
            filtered_comms = [c for c in all_communications if c.sender == 'Driver']
        
        for comm in filtered_comms:
            if comm.sender == 'System':
                icon = "🤖"
                bg_color = "#e8f4fd"
                border_color = "#1e88e5"
            elif comm.sender == 'Driver':
                icon = "🚑"
                bg_color = "#e8f5e8"
                border_color = "#4caf50"
            else:
                icon = "👨‍⚕️"
                bg_color = "#fff3e0"
                border_color = "#ff9800"
            
            with st.container():
                st.markdown(f"""
                <div style="
                    background-color: {bg_color};
                    border: 2px solid {border_color};
                    border-radius: 10px;
                    padding: 15px;
                    margin: 10px 0;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                ">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <div>
                            <strong>{icon} {comm.sender}</strong> → <strong>{comm.receiver}</strong>
                        </div>
                        <div style="font-size: 0.8em; color: #666;">
                            {comm.timestamp.strftime('%Y-%m-%d %H:%M')}
                        </div>
                    </div>
                    <div style="margin: 10px 0; padding: 10px; background: white; border-radius: 5px;">
                        {comm.message}
                    </div>
                    <div style="font-size: 0.8em; color: #888;">
                        Patient: {comm.patient_id or 'N/A'} | 
                        Ambulance: {comm.ambulance_id or 'N/A'} | 
                        Type: {comm.message_type or 'General'}
                    </div>
                </div>
                """, unsafe_allow_html=True)
    
    def send_custom_message(self):
        st.subheader("✉️ Send Custom Message")
        with st.form("custom_message_form"):
            patients = self.db.get_all_patients()
            ambulances = self.db.get_all_ambulances()
            
            col1, col2 = st.columns(2)
            with col1:
                patient_options = ["Select Patient"] + [f"{p.patient_id} - {p.name}" for p in patients]
                selected_patient = st.selectbox("Related Patient", patient_options)
                
                sender = st.selectbox("Sender", 
                    ["System", st.session_state.user.get('name', st.session_state.user['role'])])
                
            with col2:
                ambulance_options = ["Select Ambulance"] + [f"{a.ambulance_id} - {a.driver_name}" for a in ambulances]
                selected_ambulance = st.selectbox("Related Ambulance", ambulance_options)
                
                receiver_options = ["Select Receiver"] + [a.driver_name for a in ambulances] + list(hospitals_data['facility_name'])
                receiver = st.selectbox("Receiver", receiver_options)
            
            message_type = st.selectbox("Message Type", 
                ["General", "Urgent", "Update", "Emergency", "Instruction"])
            
            message = st.text_area("Message", height=150, 
                placeholder="Type your message here...")
            
            col1, col2 = st.columns(2)
            with col1:
                priority = st.selectbox("Priority", ["Normal", "High", "Urgent"])
            with col2:
                require_confirmation = st.checkbox("Require Confirmation", value=False)
            
            submitted = st.form_submit_button("Send Message", use_container_width=True)
            if submitted:
                if not message or receiver == "Select Receiver":
                    st.error("Please fill in all required fields")
                else:
                    patient_id = selected_patient.split(" - ")[0] if selected_patient != "Select Patient" else None
                    ambulance_id = selected_ambulance.split(" - ")[0] if selected_ambulance != "Select Ambulance" else None
                    
                    comm_data = {
                        'patient_id': patient_id,
                        'ambulance_id': ambulance_id,
                        'sender': sender,
                        'receiver': receiver,
                        'message': message,
                        'message_type': f"manual_{message_type.lower()}"
                    }
                    self.db.add_communication(comm_data)
                    
                    st.success(f"✅ Message sent to {receiver}")
                    
                    if require_confirmation:
                        st.info("📬 Confirmation request sent with the message")

    def message_templates(self):
        st.subheader("📋 Message Templates")
        
        template_categories = {
            "Emergency": {
                "Cardiac Emergency": "🚨 CARDIAC EMERGENCY: Patient with chest pain and suspected MI. Prepare cath lab and emergency team. ETA 15 minutes.",
                "Trauma Alert": "🚨 TRAUMA ALERT: Multiple trauma patient incoming. Activate trauma team. ETA 10 minutes.",
                "Stroke Alert": "🚨 STROKE ALERT: Patient with acute neurological symptoms. Prepare stroke team and CT scan. ETA 12 minutes."
            },
            "Status Updates": {
                "ETA Update": "📍 ETA UPDATE: Current ETA revised to {eta} minutes. Patient condition {condition}.",
                "Delay Notification": "⏱️ DELAY: Experiencing {reason}. Revised ETA {eta} minutes.",
                "Arrival Imminent": "🎯 ARRIVAL IMMINENT: Ambulance arriving in 5 minutes. Please meet at emergency entrance."
            },
            "Medical Updates": {
                "Vitals Update": "📊 VITALS UPDATE: BP {bp}, HR {hr}, SpO2 {spo2}. Patient condition {condition}.",
                "Medication Administered": "💊 MEDICATION: Administered {medication}. Patient response: {response}.",
                "Condition Change": "🔄 CONDITION CHANGE: Patient condition has {change}. New symptoms: {symptoms}."
            }
        }
        
        selected_category = st.selectbox("Select Category", list(template_categories.keys()))
        
        if selected_category:
            st.subheader(f"{selected_category} Templates")
            
            for template_name, template_content in template_categories[selected_category].items():
                col1, col2, col3 = st.columns([3, 1, 1])
                with col1:
                    st.text_area(f"{template_name}", template_content, height=100, key=f"template_{template_name}")
                with col2:
                    if st.button("Use", key=f"use_{template_name}", use_container_width=True):
                        st.session_state.selected_template = template_content
                        st.success("Template copied to message composer!")
                with col3:
                    if st.button("Edit", key=f"edit_{template_name}", use_container_width=True):
                        st.session_state.editing_template = template_name
        
        st.subheader("Create Custom Template")
        with st.form("custom_template_form"):
            template_name = st.text_input("Template Name")
            template_content = st.text_area("Template Content", height=100)
            category = st.selectbox("Category", list(template_categories.keys()) + ["Custom"])
            
            if st.form_submit_button("Save Template", use_container_width=True):
                if template_name and template_content:
                    st.success(f"Template '{template_name}' saved successfully!")
                else:
                    st.error("Please provide both template name and content")

    def notification_log(self):
        st.subheader("📊 Notification Statistics")
        
        communications = self.db.session.query(Communication).all()
        
        if not communications:
            st.info("No notifications found")
            return
        
        total_messages = len(communications)
        automatic_messages = len([c for c in communications if c.sender == 'System'])
        driver_messages = len([c for c in communications if c.sender == 'Driver'])
        manual_messages = total_messages - automatic_messages - driver_messages
        
        today = datetime.now().date()
        today_messages = len([c for c in communications if c.timestamp.date() == today])
        
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Messages", total_messages)
        with col2:
            st.metric("Automatic Notifications", automatic_messages)
        with col3:
            st.metric("Driver Messages", driver_messages)
        with col4:
            st.metric("Today's Messages", today_messages)
        
        st.subheader("Message Type Distribution")
        message_types = {}
        for comm in communications:
            msg_type = comm.message_type or 'unknown'
            message_types[msg_type] = message_types.get(msg_type, 0) + 1
        
        if message_types:
            fig = px.pie(values=list(message_types.values()), names=list(message_types.keys()),
                        title="Message Types Distribution")
            st.plotly_chart(fig, use_container_width=True)
        
        st.subheader("Recent Notification Activity")
        recent_comms = sorted(communications, key=lambda x: x.timestamp, reverse=True)[:10]
        
        for comm in recent_comms:
            status_color = "🟢" if comm.sender == 'System' else "🔵" if comm.sender == 'Driver' else "🟡"
            st.write(f"{status_color} **{comm.timestamp.strftime('%H:%M')}** - {comm.sender} → {comm.receiver}: {comm.message_type}")

# =============================================================================
# ENHANCED DRIVER UI WITH NOTIFICATIONS
# =============================================================================
class DriverUI:
    def __init__(self, db, notification_service):
        self.db = db
        self.notification_service = notification_service
        self.location_simulator = LocationSimulator(db)
    
    def display_driver_dashboard(self):
        st.header("🚑 Ambulance Driver Dashboard")
        driver_name = st.session_state.user.get('name', st.session_state.user['role'])
        ambulance = self.db.session.query(Ambulance).filter(Ambulance.driver_name == driver_name).first()
        
        if not ambulance:
            st.error("No ambulance assigned to you")
            return
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Ambulance ID", ambulance.ambulance_id)
        with col2:
            st.metric("Status", ambulance.status)
        with col3:
            st.metric("Location", ambulance.current_location)
        
        st.subheader("📨 Recent Notifications")
        driver_notifications = self.db.session.query(Communication).filter(
            Communication.receiver == driver_name
        ).order_by(Communication.timestamp.desc()).limit(5).all()
        
        if driver_notifications:
            for notification in driver_notifications:
                with st.expander(f"📬 {notification.timestamp.strftime('%H:%M')} - {notification.sender}", expanded=False):
                    st.write(notification.message)
                    if notification.patient_id:
                        patient = self.db.get_patient_by_id(notification.patient_id)
                        if patient:
                            st.write(f"**Patient:** {patient.name} - {patient.condition}")
                        
                    if notification.message_type == 'auto_driver_assignment' and ambulance.status == 'Available':
                        if st.button("Accept Assignment", key=f"accept_{notification.id}", use_container_width=True):
                            ambulance.status = 'On Transfer'
                            self.db.session.commit()
                            st.success("Assignment accepted! Proceed to patient location.")
                            st.rerun()
        else:
            st.info("No recent notifications")
        
        if ambulance.current_patient and ambulance.status == 'On Transfer':
            patient = self.db.get_patient_by_id(ambulance.current_patient)
            if patient:
                st.subheader("Current Mission")
                col1, col2 = st.columns(2)
                with col1:
                    st.write(f"**Patient:** {patient.name}")
                    st.write(f"**Condition:** {patient.condition}")
                    st.write(f"**From:** {patient.referring_hospital}")
                    st.write(f"**To:** {patient.receiving_hospital}")
                    st.write(f"**Status:** {patient.status}")
                
                with col2:
                    st.subheader("📍 Real-time Location Sharing")
                    
                    if ambulance.latitude and ambulance.longitude:
                        map_data = pd.DataFrame({
                            'lat': [ambulance.latitude, patient.referring_hospital_lat, patient.receiving_hospital_lat],
                            'lon': [ambulance.longitude, patient.referring_hospital_lng, patient.receiving_hospital_lng],
                            'name': ['Ambulance', 'Referring Hospital', 'Receiving Hospital']
                        })
                        st.map(map_data, use_container_width=True)
                    
                    st.subheader("📍 Update Location")
                    with st.form("location_update_form"):
                        new_lat = st.number_input("Latitude", value=ambulance.latitude or -0.0916)
                        new_lng = st.number_input("Longitude", value=ambulance.longitude or 34.7680)
                        location_name = st.text_input("Location Name", value=ambulance.current_location or "En route")
                        
                        if st.form_submit_button("Update Location", use_container_width=True):
                            ambulance_service = AmbulanceService(self.db)
                            if ambulance_service.update_ambulance_location(
                                ambulance.ambulance_id, new_lat, new_lng, location_name, patient.patient_id
                            ):
                                st.success("Location updated! Hospitals can now see your current position.")
                
                st.subheader("💬 Real-time Communication")
                self.display_communication_panel(patient, ambulance)
                
                st.subheader("Quick Actions")
                col1, col2, col3 = st.columns(3)
                with col1:
                    if st.button("📝 Update Vitals", use_container_width=True):
                        self.show_vitals_form(patient)
                with col2:
                    if st.button("📍 Update Location", use_container_width=True):
                        self.update_location_form(ambulance)
                with col3:
                    if st.button("🆘 Emergency", use_container_width=True, type="secondary"):
                        self.send_emergency_alert(ambulance, patient)
                
                st.subheader("Mission Completion")
                if st.button("✅ Mark Patient Delivered", use_container_width=True, type="primary"):
                    self.complete_mission(ambulance, patient)
        
        elif ambulance.status == 'Available':
            st.info("Awaiting assignment...")
            available_patients = self.db.session.query(Patient).filter(
                Patient.status == 'Referred',
                Patient.assigned_ambulance.is_(None)
            ).all()
            
            if available_patients:
                st.subheader("Available Missions")
                for patient in available_patients:
                    with st.expander(f"Mission: {patient.name} - {patient.condition}"):
                        st.write(f"**From:** {patient.referring_hospital}")
                        st.write(f"**To:** {patient.receiving_hospital}")
                        if st.button("Accept Mission", key=f"accept_{patient.patient_id}", use_container_width=True):
                            ambulance.current_patient = patient.patient_id
                            ambulance.status = 'On Transfer'
                            patient.assigned_ambulance = ambulance.ambulance_id
                            patient.status = 'Ambulance Dispatched'
                            self.db.session.commit()
                            
                            if patient.referring_hospital_lat and patient.receiving_hospital_lat:
                                thread = threading.Thread(
                                    target=self.location_simulator.start_simulation,
                                    args=(
                                        ambulance.ambulance_id,
                                        patient.patient_id,
                                        ambulance.latitude,
                                        ambulance.longitude,
                                        patient.receiving_hospital_lat,
                                        patient.receiving_hospital_lng
                                    )
                                )
                                thread.daemon = True
                                thread.start()
                            
                            st.success(f"Mission accepted! Assigned to patient {patient.name}")
                            st.rerun()
        
        st.subheader("Quick Status Updates")
        self.quick_actions(ambulance)
    
    def display_communication_panel(self, patient, ambulance):
        col1, col2 = st.columns([2, 1])
        
        with col1:
            st.subheader("Chat with Hospitals")
            
            communications = self.db.get_communications_for_patient(patient.patient_id)
            if communications:
                st.write("**Recent Messages:**")
                for comm in communications[:5]:
                    timestamp = comm.timestamp.strftime('%H:%M')
                    if comm.sender == 'Driver':
                        st.markdown(f"**You** ({timestamp}): {comm.message}")
                    else:
                        st.markdown(f"**{comm.sender}** ({timestamp}): {comm.message}")
            else:
                st.info("No messages yet")
            
            with st.form("message_form"):
                message = st.text_area("Type your message", placeholder="Update on patient condition, ETA, or any issues...")
                recipient = st.selectbox("Send to", 
                    [patient.referring_hospital, patient.receiving_hospital, "Both Hospitals"])
                if st.form_submit_button("Send Message", use_container_width=True):
                    if message:
                        if recipient == "Both Hospitals":
                            hospitals = [patient.referring_hospital, patient.receiving_hospital]
                        else:
                            hospitals = [recipient]
                        
                        for hospital in hospitals:
                            comm_data = {
                                'patient_id': patient.patient_id,
                                'ambulance_id': ambulance.ambulance_id,
                                'sender': 'Driver',
                                'receiver': hospital,
                                'message': message,
                                'message_type': 'driver_hospital'
                            }
                            self.db.add_communication(comm_data)
                        
                        st.success("Message sent!")
                        st.rerun()
                    else:
                        st.error("Please enter a message")
        
        with col2:
            st.subheader("Quick Updates")
            
            quick_messages = {
                "ETA 10 mins": "Estimated arrival in 10 minutes",
                "Patient stable": "Patient condition is stable during transport",
                "Traffic delay": "Experiencing traffic delays, will update ETA",
                "Need assistance": "Require medical assistance upon arrival",
                "Vitals normal": "Patient vital signs are within normal range"
            }
            
            for label, message in quick_messages.items():
                if st.button(label, key=f"quick_{label}", use_container_width=True):
                    for hospital in [patient.referring_hospital, patient.receiving_hospital]:
                        comm_data = {
                            'patient_id': patient.patient_id,
                            'ambulance_id': ambulance.ambulance_id,
                            'sender': 'Driver',
                            'receiver': hospital,
                            'message': f"Quick update: {message}",
                            'message_type': 'driver_hospital'
                        }
                        self.db.add_communication(comm_data)
                    st.success("Quick update sent!")
    
    def show_vitals_form(self, patient):
        with st.form("vitals_form"):
            st.subheader("Update Patient Vitals")
            bp = st.text_input("Blood Pressure", value="120/80")
            heart_rate = st.number_input("Heart Rate (bpm)", min_value=0, max_value=200, value=72)
            spo2 = st.number_input("Oxygen Saturation (%)", min_value=0, max_value=100, value=98)
            respiratory_rate = st.number_input("Respiratory Rate", min_value=0, max_value=60, value=16)
            notes = st.text_area("Observations")
            if st.form_submit_button("Update Vitals", use_container_width=True):
                patient.vital_signs = {
                    'blood_pressure': bp, 
                    'heart_rate': heart_rate, 
                    'oxygen_saturation': spo2,
                    'respiratory_rate': respiratory_rate,
                    'notes': notes, 
                    'timestamp': datetime.utcnow().isoformat()
                }
                self.db.session.commit()
                
                for hospital in [patient.referring_hospital, patient.receiving_hospital]:
                    comm_data = {
                        'patient_id': patient.patient_id,
                        'sender': 'Driver',
                        'receiver': hospital,
                        'message': f"Vitals updated: BP {bp}, HR {heart_rate}bpm, SpO2 {spo2}%",
                        'message_type': 'vitals_update'
                    }
                    self.db.add_communication(comm_data)
                
                st.success("Vitals updated and notified hospitals!")
    
    def update_location_form(self, ambulance):
        with st.form("location_form"):
            st.subheader("Update Current Location")
            location_name = st.text_input("Location Name", value=ambulance.current_location)
            latitude = st.number_input("Latitude", value=ambulance.latitude or -0.0916)
            longitude = st.number_input("Longitude", value=ambulance.longitude or 34.7680)
            if st.form_submit_button("Update Location", use_container_width=True):
                ambulance_service = AmbulanceService(self.db)
                if ambulance_service.update_ambulance_location(
                    ambulance.ambulance_id, latitude, longitude, location_name, ambulance.current_patient
                ):
                    st.success("Location updated! Hospitals can now see your current position.")
    
    def send_emergency_alert(self, ambulance, patient):
        st.error("🚨 EMERGENCY ALERT SENT!")
        emergency_message = f"EMERGENCY: Ambulance {ambulance.ambulance_id} requires immediate assistance!"
        
        recipients = [patient.referring_hospital, patient.receiving_hospital, "Control Center"]
        for recipient in recipients:
            comm_data = {
                'patient_id': patient.patient_id,
                'ambulance_id': ambulance.ambulance_id,
                'sender': 'Driver',
                'receiver': recipient,
                'message': emergency_message,
                'message_type': 'emergency'
            }
            self.db.add_communication(comm_data)
        
        self.notification_service.send_notification(
            "Control Center",
            emergency_message,
            'emergency'
        )
    
    def complete_mission(self, ambulance, patient):
        referral_service = ReferralService(self.db, self.notification_service)
        referral_service.complete_mission(ambulance, patient)
        st.rerun()
    
    def quick_actions(self, ambulance):
        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button("🔄 Mark Available", use_container_width=True):
                ambulance.status = 'Available'
                ambulance.current_patient = None
                self.db.session.commit()
                st.success("Status updated to Available")
                st.rerun()
        with col2:
            if st.button("⛑️ Mark On Break", use_container_width=True):
                ambulance.status = 'On Break'
                self.db.session.commit()
                st.success("Status updated to On Break")
                st.rerun()
        with col3:
            if st.button("🔧 Maintenance", use_container_width=True):
                ambulance.status = 'Maintenance'
                self.db.session.commit()
                st.success("Status updated to Maintenance")
                st.rerun()

# =============================================================================
# OTHER UI CLASSES (HandoverUI, ReportsUI)
# =============================================================================
class HandoverUI:
    def __init__(self, db):
        self.db = db
    
    def display(self):
        st.title("📄 Patient Handover Management")
        tab1, tab2 = st.tabs(["Create Handover Form", "Handover History"])
        with tab1:
            self.create_handover_form()
        with tab2:
            self.display_handover_history()
    
    def create_handover_form(self):
        st.subheader("Create Handover Form")
        patients = self.db.get_all_patients()
        user_hospital = st.session_state.user['hospital']
        
        if user_hospital == "All Facilities":
            eligible_patients = [p for p in patients if p.status == 'Arrived at Destination']
        else:
            eligible_patients = [p for p in patients if p.receiving_hospital == user_hospital and p.status == 'Arrived at Destination']
            
        if not eligible_patients:
            st.info("No patients eligible for handover (must have status 'Arrived at Destination')")
            return
        
        patient_options = {f"{p.patient_id} - {p.name}": p for p in eligible_patients}
        selected_patient_key = st.selectbox("Select Patient", list(patient_options.keys()))
        selected_patient = patient_options[selected_patient_key]
        
        with st.form("handover_form", clear_on_submit=True):
            st.write(f"**Patient:** {selected_patient.name}")
            st.write(f"**Condition:** {selected_patient.condition}")
            st.write(f"**From:** {selected_patient.referring_hospital}")
            st.write(f"**To:** {selected_patient.receiving_hospital}")
            
            st.subheader("Vital Signs at Handover")
            col1, col2 = st.columns(2)
            with col1:
                blood_pressure = st.text_input("Blood Pressure", value="120/80")
                heart_rate = st.number_input("Heart Rate (bpm)", min_value=0, max_value=200, value=72)
            with col2:
                temperature = st.number_input("Temperature (°C)", min_value=30.0, max_value=45.0, value=36.6)
                oxygen_saturation = st.number_input("Oxygen Saturation (%)", min_value=0, max_value=100, value=98)
            
            st.subheader("Handover Details")
            receiving_physician = st.text_input("Receiving Physician*")
            handover_notes = st.text_area("Handover Notes")
            
            with st.expander("Additional Information"):
                condition_changes = st.text_area("Condition Changes During Transfer")
                interventions = st.text_area("Interventions During Transfer")
                medications_administered = st.text_area("Medications Administered")
            
            submitted = st.form_submit_button("Complete Handover", use_container_width=True)
            if submitted:
                if not receiving_physician:
                    st.error("Please enter the receiving physician")
                else:
                    handover_data = {
                        'patient_id': selected_patient.patient_id, 'patient_name': selected_patient.name,
                        'age': selected_patient.age, 'condition': selected_patient.condition,
                        'referring_hospital': selected_patient.referring_hospital,
                        'receiving_hospital': selected_patient.receiving_hospital,
                        'referring_physician': selected_patient.referring_physician,
                        'receiving_physician': receiving_physician, 'vital_signs': {
                            'blood_pressure': blood_pressure, 'heart_rate': heart_rate,
                            'temperature': temperature, 'oxygen_saturation': oxygen_saturation
                        }, 'medical_history': selected_patient.medical_history,
                        'current_medications': selected_patient.current_medications,
                        'allergies': selected_patient.allergies, 'notes': handover_notes,
                        'ambulance_id': selected_patient.assigned_ambulance,
                        'created_by': st.session_state.user['role']
                    }
                    handover = self.db.add_handover_form(handover_data)
                    selected_patient.status = 'Completed'
                    selected_patient.receiving_physician = receiving_physician
                    self.db.session.commit()
                    st.success("Handover completed successfully!")
                    st.balloons()
    
    def display_handover_history(self):
        st.subheader("Handover History")
        handovers = self.db.session.query(HandoverForm).all()
        user_hospital = st.session_state.user['hospital']
        
        if user_hospital != "All Facilities":
            handovers = [h for h in handovers if h.receiving_hospital == user_hospital]
            
        if handovers:
            for handover in handovers:
                with st.expander(f"{handover.patient_name} - {handover.transfer_time.strftime('%Y-%m-%d %H:%M')}"):
                    col1, col2 = st.columns(2)
                    with col1:
                        st.write(f"**Patient ID:** {handover.patient_id}")
                        st.write(f"**Age:** {handover.age}")
                        st.write(f"**Condition:** {handover.condition}")
                        st.write(f"**Referring Hospital:** {handover.referring_hospital}")
                        st.write(f"**Receiving Hospital:** {handover.receiving_hospital}")
                    with col2:
                        st.write(f"**Referring Physician:** {handover.referring_physician}")
                        st.write(f"**Receiving Physician:** {handover.receiving_physician}")
                        st.write(f"**Ambulance:** {handover.ambulance_id}")
                        st.write(f"**Handover Time:** {handover.transfer_time.strftime('%Y-%m-%d %H:%M')}")
                    
                    if handover.vital_signs:
                        st.subheader("Vital Signs at Handover")
                        vitals = handover.vital_signs
                        col1, col2, col3, col4 = st.columns(4)
                        with col1:
                            st.metric("BP", vitals.get('blood_pressure', 'N/A'))
                        with col2:
                            st.metric("HR", f"{vitals.get('heart_rate', 'N/A')} bpm")
                        with col3:
                            st.metric("Temp", f"{vitals.get('temperature', 'N/A')}°C")
                        with col4:
                            st.metric("SpO2", f"{vitals.get('oxygen_saturation', 'N/A')}%")
                    
                    if handover.notes:
                        st.write(f"**Handover Notes:** {handover.notes}")
        else:
            st.info("No handover forms completed")

class ReportsUI:
    def __init__(self, db, analytics):
        self.db = db
        self.analytics = analytics
        self.pdf_exporter = PDFExporter()
    
    def display(self):
        st.title("📈 Reports & Analytics")
        tab1, tab2, tab3, tab4 = st.tabs(["Performance Metrics", "Hospital Analytics", "Ambulance Reports", "Export Data"])
        with tab1:
            self.performance_metrics()
        with tab2:
            self.hospital_analytics()
        with tab3:
            self.ambulance_reports()
        with tab4:
            self.export_data()
    
    def performance_metrics(self):
        st.subheader("Performance Metrics")
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input("Start Date", datetime.now() - timedelta(days=30))
        with col2:
            end_date = st.date_input("End Date", datetime.now())
        
        kpis = self.analytics.get_kpis()
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Referrals", kpis['total_referrals'])
        with col2:
            st.metric("Completion Rate", kpis['completion_rate'])
        with col3:
            st.metric("Avg Response Time", kpis['avg_response_time'])
        with col4:
            st.metric("Active Transfers", kpis['active_referrals'])
        
        st.subheader("Response Time Trends")
        dates = pd.date_range(start=start_date, end=end_date, freq='D')
        response_times = [15 + i % 5 for i in range(len(dates))]
        response_df = pd.DataFrame({'Date': dates, 'Response Time (min)': response_times})
        fig = px.line(response_df, x='Date', y='Response Time (min)', title="Average Response Time Trend")
        st.plotly_chart(fig, use_container_width=True, key="response_time_chart")
        
        st.subheader("Referral Reasons")
        patients = self.db.get_all_patients()
        if patients:
            conditions = [p.condition for p in patients]
            condition_counts = pd.Series(conditions).value_counts()
            fig = px.pie(values=condition_counts.values, names=condition_counts.index,
                        title="Referral Reasons Distribution")
            st.plotly_chart(fig, use_container_width=True, key="referral_reasons_chart")
    
    def hospital_analytics(self):
        st.subheader("Hospital Performance")
        hospitals_stats = self.analytics.get_hospital_stats()
        if not hospitals_stats.empty:
            hospital_referrals = hospitals_stats.groupby('hospital')['count'].sum().reset_index()
            fig = px.bar(hospital_referrals, x='hospital', y='count', title="Total Referrals by Hospital")
            st.plotly_chart(fig, use_container_width=True, key="hospital_referrals_chart")
            
            fig = px.sunburst(hospitals_stats, path=['hospital', 'status'], values='count',
                             title="Referral Status by Hospital")
            st.plotly_chart(fig, use_container_width=True, key="hospital_status_chart")
        else:
            st.info("No hospital data available")
    
    def ambulance_reports(self):
        st.subheader("Ambulance Utilization")
        ambulances = self.db.get_all_ambulances()
        if ambulances:
            status_counts = {}
            for ambulance in ambulances:
                status_counts[ambulance.status] = status_counts.get(ambulance.status, 0) + 1
            
            fig = px.pie(values=list(status_counts.values()), names=list(status_counts.keys()),
                        title="Ambulance Status Distribution")
            st.plotly_chart(fig, use_container_width=True, key="ambulance_status_pie_chart")
            
            st.subheader("Ambulance Utilization Details")
            ambulance_data = []
            for ambulance in ambulances:
                utilization = "High" if ambulance.status != 'Available' else "Low"
                ambulance_data.append({
                    'Ambulance ID': ambulance.ambulance_id, 'Driver': ambulance.driver_name,
                    'Status': ambulance.status, 'Utilization': utilization,
                    'Current Patient': ambulance.current_patient or 'None', 'Location': ambulance.current_location
                })
            st.dataframe(pd.DataFrame(ambulance_data), use_container_width=True)
        else:
            st.info("No ambulance data available")
    
    def export_data(self):
        st.subheader("Data Export")
        col1, col2 = st.columns(2)
        with col1:
            st.download_button(
                label="📊 Export Referrals as CSV",
                data=self.export_referrals_csv(),
                file_name=f"referrals_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv",
                use_container_width=True
            )
            st.download_button(
                label="🚑 Export Ambulance Data as CSV",
                data=self.export_ambulances_csv(),
                file_name=f"ambulances_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv",
                use_container_width=True
            )
        with col2:
            if st.button("📄 Generate PDF Report", use_container_width=True):
                st.info("PDF report generation feature would be implemented here")
            if st.button("📈 Export Analytics", use_container_width=True):
                st.info("Analytics export feature would be implemented here")
    
    def export_referrals_csv(self):
        patients = self.db.get_all_patients()
        data = []
        for patient in patients:
            data.append({
                'Patient ID': patient.patient_id, 'Name': patient.name, 'Age': patient.age,
                'Condition': patient.condition, 'Referring Hospital': patient.referring_hospital,
                'Receiving Hospital': patient.receiving_hospital, 'Status': patient.status,
                'Referral Time': patient.referral_time, 'Assigned Ambulance': patient.assigned_ambulance
            })
        df = pd.DataFrame(data)
        return df.to_csv(index=False)
    
    def export_ambulances_csv(self):
        ambulances = self.db.get_all_ambulances()
        data = []
        for ambulance in ambulances:
            data.append({
                'Ambulance ID': ambulance.ambulance_id, 'Driver': ambulance.driver_name,
                'Contact': ambulance.driver_contact, 'Status': ambulance.status,
                'Location': ambulance.current_location, 'Current Patient': ambulance.current_patient
            })
        df = pd.DataFrame(data)
        return df.to_csv(index=False)

# =============================================================================
# ENHANCED MAIN APPLICATION
# =============================================================================
class HospitalReferralApp:
    def __init__(self):
        self.auth = Authentication()
        self.db = Database()
        initialize_sample_data(self.db)
        self.analytics = AnalyticsService(self.db)
        self.notifications = NotificationService(self.db)
        self.dashboard_ui = DashboardUI(self.db, self.analytics)
        self.referral_ui = ReferralUI(self.db, self.notifications)
        self.tracking_ui = TrackingUI(self.db)
        self.handover_ui = HandoverUI(self.db)
        self.communication_ui = CommunicationUI(self.db, self.notifications)
        self.reports_ui = ReportsUI(self.db, self.analytics)
        self.driver_ui = DriverUI(self.db, self.notifications)
        self.cost_management_ui = CostManagementUI(self.db, self.analytics)
        
        if 'authenticated' not in st.session_state:
            st.session_state.authenticated = False
        if 'user' not in st.session_state:
            st.session_state.user = None
        if 'simulation_running' not in st.session_state:
            st.session_state.simulation_running = False
    
    def run(self):
        self.auth.setup_auth_ui()
        if st.session_state.get('authenticated'):
            self.render_main_app()
        else:
            self.render_login_page()
    
    def render_login_page(self):
        st.title("🏥 Kisumu County Hospital Referral System")
        st.markdown("""
        ## Welcome to the Hospital Referral & Ambulance Tracking System
        
        Please login using the sidebar to access the system.
        
        **Demo Credentials:**
        - Admin: `admin` / `admin123`
        - Hospital Staff (JOOTRH): `hospital_staff` / `staff123`
        - Hospital Staff (Kisumu County): `kisumu_staff` / `kisumu123`
        - Ambulance Driver: `driver` / `driver123`
        """)
        
        st.subheader("System Overview")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Hospitals in Network", "40")
        with col2:
            st.metric("Ambulances", "20")
        with col3:
            st.metric("Coverage Area", "Kisumu County")
        
        st.subheader("Referral Rules")
        st.markdown("""
        - **Jaramogi Oginga Odinga Teaching & Referral Hospital (JOOTRH)**: Can receive referrals only
        - **Kisumu County Referral Hospital**: Can both refer and receive patients
        - **Other 38 Hospitals**: Can only refer patients to the two referral hospitals
        """)
    
    def render_main_app(self):
        user_role = st.session_state.user['role']
        user_name = st.session_state.user.get('name', st.session_state.user['role'])
        
        st.sidebar.markdown("---")
        st.sidebar.info(f"**Logged in as:** {user_name}\n\n**Role:** {user_role}\n\n**Hospital:** {st.session_state.user['hospital']}")
        
        if user_role == 'Admin':
            self.render_admin_interface()
        elif user_role == 'Hospital Staff':
            self.render_staff_interface()
        elif user_role == 'Ambulance Driver':
            self.render_driver_interface()
        
        st.markdown("---")
        st.markdown("**Kisumu County Hospital Referral System** | Secure • Reliable • Cost-Efficient")
    
    def render_admin_interface(self):
        st.sidebar.title("Admin Navigation")
        tabs = st.tabs([
            "📊 Dashboard", "📋 Referrals", "🚑 Tracking", "💰 Cost Management",
            "📄 Handovers", "💬 Communication", "📈 Reports", "👥 User Management"
        ])
        with tabs[0]:
            self.dashboard_ui.display()
        with tabs[1]:
            self.referral_ui.display()
        with tabs[2]:
            self.tracking_ui.display()
        with tabs[3]:
            self.cost_management_ui.display()
        with tabs[4]:
            self.handover_ui.display()
        with tabs[5]:
            self.communication_ui.display()
        with tabs[6]:
            self.reports_ui.display()
        with tabs[7]:
            self.render_user_management()
    
    def render_staff_interface(self):
        st.sidebar.title("Staff Navigation")
        user_hospital = st.session_state.user['hospital']
        
        if user_hospital == "Kisumu County Referral Hospital":
            tabs = st.tabs([
                "📊 Dashboard", "📋 Create Referral", "🚑 Tracking", "📄 Handovers", "💬 Communication"
            ])
        else:
            tabs = st.tabs([
                "📊 Dashboard", "📋 Referrals", "🚑 Tracking", "📄 Handovers", "💬 Communication"
            ])
            
        with tabs[0]:
            self.dashboard_ui.display()
        with tabs[1]:
            self.referral_ui.display()
        with tabs[2]:
            self.tracking_ui.display()
        with tabs[3]:
            self.handover_ui.display()
        with tabs[4]:
            self.communication_ui.display()
    
    def render_driver_interface(self):
        self.driver_ui.display_driver_dashboard()
    
    def render_user_management(self):
        if self.auth.require_auth(['Admin']):
            st.header("👥 User Management")
            col1, col2 = st.columns(2)
            with col1:
                st.subheader("Add New User")
                with st.form("add_user_form"):
                    username = st.text_input("Username")
                    password = st.text_input("Password", type="password")
                    email = st.text_input("Email")
                    role = st.selectbox("Role", ["Admin", "Hospital Staff", "Ambulance Driver"])
                    hospital = st.selectbox("Hospital", ["All Facilities", "Jaramogi Oginga Odinga Teaching & Referral Hospital (JOOTRH)", "Kisumu County Referral Hospital"] + hospitals_data['facility_name'][2:])
                    if st.form_submit_button("Add User", use_container_width=True):
                        st.success(f"User {username} added successfully")
            with col2:
                st.subheader("Current Users")
                users_data = [
                    {"Username": "admin", "Role": "Admin", "Hospital": "All Facilities"},
                    {"Username": "hospital_staff", "Role": "Hospital Staff", "Hospital": "JOOTRH"},
                    {"Username": "kisumu_staff", "Role": "Hospital Staff", "Hospital": "Kisumu County Referral Hospital"},
                    {"Username": "driver", "Role": "Ambulance Driver", "Hospital": "Ambulance Service"}
                ]
                st.dataframe(users_data)

# =============================================================================
# RUN APPLICATION
# =============================================================================
if __name__ == "__main__":
    st.set_page_config(
        page_title=Config.PAGE_TITLE,
        page_icon=Config.PAGE_ICON,
        layout=Config.LAYOUT,
        initial_sidebar_state="expanded"
    )
    
    st.markdown("""
    <style>
    .main-header {
        font-size: 2.5rem;
        color: #1f77b4;
        text-align: center;
        margin-bottom: 2rem;
    }
    .metric-card {
        background-color: #f0f2f6;
        padding: 1rem;
        border-radius: 10px;
        border-left: 5px solid #1f77b4;
    }
    .stButton button {
        width: 100%;
    }
    </style>
    """, unsafe_allow_html=True)
    
    app = HospitalReferralApp()
    app.run()
