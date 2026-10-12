"""
BloodLink - BTech 2nd-Year Mini Project
Flask Backend for Blood Availability and Hospital Request System
Flow: Home -> Find Blood Form -> User Details -> Closest Hospitals with Availability -> Request Blood -> Thank You
"""

import os
import csv
import math
import time
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from dotenv import load_dotenv
from supabase import create_client


app = Flask(
    __name__,
    template_folder='.',
    static_folder='.',
    static_url_path=''
)

app.secret_key = 'bloodlink-btech-secret-key'

# -------------------------------------------------------------
# Supabase Configuration
# -------------------------------------------------------------
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Supabase credentials not found in .env")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


# Valid standard blood groups
VALID_BLOOD_GROUPS = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]

# Paths to the CSV datasets
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
INVENTORY_CSV = os.path.join(DATA_DIR, 'BloodLink_Blood_Inventory.csv')
HOSPITALS_CSV = os.path.join(DATA_DIR, 'BloodLink_Hospitals.csv')

# Coordinate reference mapping for common Panvel / Navi Mumbai localities
LOCATION_COORDS = {
    "panvel": (18.9895, 73.1190),
    "old panvel": (18.9917, 73.1102),
    "new panvel": (18.9990, 73.1180),
    "khanda": (18.9975, 73.1010),
    "khanda colony": (18.9975, 73.1010),
    "kharghar": (19.0474, 73.0664),
    "kamothe": (19.0186, 73.0952),
    "lodhivali": (18.9500, 73.2200),
    "vichumbe": (18.9700, 73.1400),
    "sector 19": (19.0005, 73.1200),
    "sector 15": (18.9990, 73.1220),
    "sector 8": (18.9950, 73.1160),
    "sector 6": (18.9975, 73.1010),
    "uran road": (18.9895, 73.1105),
    "station": (18.9922, 73.1095)
}
DEFAULT_USER_COORDS = (18.9900, 73.1150)  # Central Panvel fallback coordinates


def haversine_distance(lat1, lon1, lat2, lon2):
    """
    Calculates the great-circle distance between two points on the Earth (in km)
    using the Haversine formula.
    """
    try:
        lat1, lon1, lat2, lon2 = float(lat1), float(lon1), float(lat2), float(lon2)
    except (ValueError, TypeError):
        return None

    r = 6371.0  # Earth radius in kilometers
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return round(r * c, 1)


def resolve_location_coords(location_str, user_lat=None, user_lon=None):
    """
    Resolves geographic coordinates from either user geolocation or entered text location.
    """
    if user_lat and user_lon:
        try:
            return float(user_lat), float(user_lon)
        except (ValueError, TypeError):
            pass

    if not location_str:
        return DEFAULT_USER_COORDS

    clean_loc = location_str.strip().lower()
    for key, coords in LOCATION_COORDS.items():
        if key in clean_loc:
            return coords

    return DEFAULT_USER_COORDS


def get_csv_path(filename):
    """Finds CSV file in data/ or root directory."""
    path_in_data = os.path.join(DATA_DIR, filename)
    if os.path.exists(path_in_data):
        return path_in_data
    path_in_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
    if os.path.exists(path_in_root):
        return path_in_root
    return None


def load_hospitals():
    """
    Loads hospitals dataset from BloodLink_Hospitals.csv.
    Columns: hospital_id, hospital_name, address, latitude, longitude, phone
    """
    csv_path = get_csv_path('BloodLink_Hospitals.csv')
    if not csv_path or not os.path.exists(csv_path):
        print("[ERROR] BloodLink_Hospitals.csv not found!")
        return {}

    hospitals = {}
    try:
        with open(csv_path, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                clean_row = {k.strip(): v.strip() for k, v in row.items() if k is not None}
                h_id = clean_row.get('hospital_id')
                if h_id:
                    hospitals[h_id] = {
                        'hospital_id': h_id,
                        'hospital_name': clean_row.get('hospital_name', 'Unknown Hospital'),
                        'address': clean_row.get('address', 'Address not available'),
                        'latitude': clean_row.get('latitude', ''),
                        'longitude': clean_row.get('longitude', ''),
                        'phone': clean_row.get('phone', 'N/A')
                    }
    except Exception as e:
        print(f"[ERROR] Failed to load hospitals CSV: {e}")
        return {}

    return hospitals

def calculate_distance(lat1, lon1, lat2, lon2):
    """Calculate approximate distance between two GPS coordinates in km."""
    R = 6371

    lat1 = math.radians(float(lat1))
    lat2 = math.radians(float(lat2))

    dlat = lat2 - lat1
    dlon = math.radians(float(lon2)) - math.radians(float(lon1))

    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1)
        * math.cos(lat2)
        * math.sin(dlon / 2) ** 2
    )

    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c

def find_closest_delivery_partner(latitude, longitude):
    """Find the closest available delivery partner."""

    response = (
        supabase
        .table("delivery_partners")
        .select("*")
        .eq("availability_status", "Available")
        .execute()
    )

    partners = response.data or []

    print("[DELIVERY] Available partners:", partners)

    if not partners:
        print("[DELIVERY] No available partners found")
        return None

    closest_partner = None
    shortest_distance = float("inf")

    for partner in partners:

        print("[DELIVERY] Checking:", partner.get("partner_name"))
        print(
            "[DELIVERY] Coordinates:",
            partner.get("current_latitude"),
            partner.get("current_longitude")
        )

        if (
            partner.get("current_latitude") is None
            or partner.get("current_longitude") is None
        ):
            continue

        try:
            partner_latitude = float(partner["current_latitude"])
            partner_longitude = float(partner["current_longitude"])

            distance = calculate_distance(
                latitude,
                longitude,
                partner_latitude,
                partner_longitude
            )

            print(
                "[DELIVERY] Distance to",
                partner["partner_name"],
                "=",
                distance,
                "km"
            )

            if distance < shortest_distance:
                shortest_distance = distance
                closest_partner = partner

        except (ValueError, TypeError) as e:
            print(
                "[DELIVERY] Coordinate error:",
                partner["partner_name"],
                e
            )

    if closest_partner:
        closest_partner["distance_km"] = round(
            shortest_distance, 2
        )

    print("[DELIVERY] FINAL PARTNER:", closest_partner)

    return closest_partner

def load_blood_inventory():
    """
    Loads blood inventory dataset from BloodLink_Blood_Inventory.csv.
    Columns: inventory_id, hospital_id, blood_group, units, status
    """
    csv_path = get_csv_path('BloodLink_Blood_Inventory.csv')
    if not csv_path or not os.path.exists(csv_path):
        print("[ERROR] BloodLink_Blood_Inventory.csv not found!")
        return []

    inventory = []
    try:
        with open(csv_path, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                clean_row = {k.strip(): v.strip() for k, v in row.items() if k is not None}
                inventory.append(clean_row)
    except Exception as e:
        print(f"[ERROR] Failed to load inventory CSV: {e}")
        return []

    return inventory

def load_delivery_partners():
    """Loads delivery partner information from CSV."""
    csv_path = get_csv_path('delivery_partners.csv')

    if not csv_path:
        print("[ERROR] delivery_partners.csv not found!")
        return []

    partners = []

    try:
        with open(csv_path, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)

            for row in reader:
                clean_row = {
                    k.strip(): v.strip()
                    for k, v in row.items()
                    if k is not None
                }
                partners.append(clean_row)

    except Exception as e:
        print(f"[ERROR] Failed to load delivery partners CSV: {e}")
        return []

    return partners


def load_deliveries():
    """Loads delivery records from CSV."""
    csv_path = get_csv_path('deliveries.csv')

    if not csv_path:
        print("[ERROR] deliveries.csv not found!")
        return []

    deliveries = []

    try:
        with open(csv_path, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)

            for row in reader:
                clean_row = {
                    k.strip(): v.strip()
                    for k, v in row.items()
                    if k is not None
                }
                deliveries.append(clean_row)

    except Exception as e:
        print(f"[ERROR] Failed to load deliveries CSV: {e}")
        return []

    return deliveries


def load_location_updates():
    """Loads delivery location updates from CSV."""
    csv_path = get_csv_path('location_updates.csv')

    if not csv_path:
        print("[ERROR] location_updates.csv not found!")
        return []

    updates = []

    try:
        with open(csv_path, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)

            for row in reader:
                clean_row = {
                    k.strip(): v.strip()
                    for k, v in row.items()
                    if k is not None
                }
                updates.append(clean_row)

    except Exception as e:
        print(f"[ERROR] Failed to load location updates CSV: {e}")
        return []

    return updates

def get_latest_location(delivery_id):
    """
    Gets the latest location of a delivery.
    For now, this simulates movement using predefined coordinates.
    """

    updates = load_location_updates()

    delivery_updates = [
        update for update in updates
        if update.get('delivery_id') == delivery_id
    ]

    if not delivery_updates:
        return None

    latest = delivery_updates[-1]

    return {
        'delivery_id': delivery_id,
        'latitude': float(latest.get('latitude', 0)),
        'longitude': float(latest.get('longitude', 0)),
        'status': latest.get('status', 'Unknown'),
        'timestamp': latest.get('timestamp', '')
    }

# -------------------------------------------------------------
# Live Delivery Location API - PostgreSQL
# -------------------------------------------------------------

@app.route('/api/delivery/<delivery_id>/location')
def delivery_location_api(delivery_id):
    try:
        # D001 -> 1
        database_delivery_id = int(
            delivery_id.replace("D", "")
        )

        # -------------------------------------------------
        # 1. Get delivery
        # -------------------------------------------------
        delivery_response = (
            supabase
            .table("deliveries")
            .select("""
                id,
                partner_id,
                customer_name,
                customer_phone,
                blood_group,
                hospital_name,
                destination,
                destination_latitude,
                destination_longitude,
                status,
                eta_minutes,
                created_at,
                updated_at
            """)
            .eq("id", database_delivery_id)
            .limit(1)
            .execute()
        )

        deliveries = delivery_response.data

        if not deliveries:
            return jsonify({
                "success": False,
                "message": "Delivery not found"
            }), 404

        delivery = deliveries[0]

        # -------------------------------------------------
        # 2. Get delivery partner
        # -------------------------------------------------
        partner = None

        if delivery["partner_id"] is not None:
            partner_response = (
                supabase
                .table("delivery_partners")
                .select("""
                    id,
                    partner_name,
                    phone,
                    vehicle_type,
                    location,
                    availability_status,
                    current_latitude,
                    current_longitude
                """)
                .eq("id", delivery["partner_id"])
                .limit(1)
                .execute()
            )

            partners = partner_response.data
            partner = partners[0] if partners else None

        # -------------------------------------------------
        # 3. Get latest GPS location
        # -------------------------------------------------
        location_response = (
            supabase
            .table("location_updates")
            .select("""
                id,
                delivery_id,
                partner_id,
                latitude,
                longitude,
                recorded_at
            """)
            .eq("delivery_id", database_delivery_id)
            .order("recorded_at", desc=True)
            .limit(1)
            .execute()
        )

        locations = location_response.data

        # -------------------------------------------------
        # 4. Use latest GPS update
        # -------------------------------------------------
        location = locations[0] if locations else None

        # If no location update exists yet,
        # use partner's current location.
        if location:
            latitude = float(location["latitude"])
            longitude = float(location["longitude"])
            recorded_at = location["recorded_at"]
        elif partner:
            latitude = float(partner["current_latitude"])
            longitude = float(partner["current_longitude"])
            recorded_at = None
        else:
            latitude = None
            longitude = None
            recorded_at = None

    
        
        # Calculate estimated travel time to destination
        eta_minutes = delivery.get("eta_minutes") or 0

        destination_lat = delivery.get("destination_latitude")
        destination_lon = delivery.get("destination_longitude")

        if (
            latitude is not None
            and longitude is not None
            and destination_lat is not None
            and destination_lon is not None
        ):
            distance_km = calculate_distance(
                latitude,
                longitude,
                float(destination_lat),
                float(destination_lon)
            )

            # Approximate city travel speed: 20 km/h
            eta_minutes = round((distance_km / 20) * 60)

            if distance_km > 0.1:
                eta_minutes = max(1, eta_minutes)
            else:
                eta_minutes = 0
        # -------------------------------------------------
        # 5. Return data to frontend
        # -------------------------------------------------
        return jsonify({
            "success": True,
            "data": {
                "delivery_id": delivery_id,
                "database_delivery_id": delivery["id"],

                "partner_id": delivery["partner_id"],

                "partner_name": (
                    partner["partner_name"]
                    if partner else None
                ),

                "phone": (
                    partner["phone"]
                    if partner else None
                ),

                "vehicle_type": (
                    partner["vehicle_type"]
                    if partner else None
                ),

                "partner_location": (
                    partner["location"]
                    if partner else None
                ),

                "latitude": latitude,
                "longitude": longitude,

                "status": delivery["status"],
                "eta_minutes": eta_minutes,

                "blood_group": delivery["blood_group"],
                "customer_name": delivery["customer_name"],
                "customer_phone": delivery["customer_phone"],

                "hospital_name": delivery["hospital_name"],
                "destination": delivery["destination"],

                "destination_latitude": (
                    float(delivery["destination_latitude"])
                    if delivery["destination_latitude"] is not None
                    else None
                ),

                "destination_longitude": (
                    float(delivery["destination_longitude"])
                    if delivery["destination_longitude"] is not None
                    else None
                ),

                "recorded_at": recorded_at
            }
        })

    except Exception as e:
        print("[ERROR] Live tracking API:", e)

        return jsonify({
            "success": False,
            "message": "Supabase database error",
            "error": str(e)
        }), 500

@app.route('/api/delivery/<delivery_id>/status', methods=['POST'])
def update_delivery_status(delivery_id):
    try:
        database_delivery_id = int(delivery_id.replace("D", ""))

        data = request.get_json(silent=True) or {}
        new_status = data.get("status", "").strip()

        allowed_statuses = [
            "Assigned",
            "On the way",
            "Arrived",
            "Completed",
            "Cancelled"
        ]

        if new_status not in allowed_statuses:
            return jsonify({
                "success": False,
                "message": "Invalid delivery status"
            }), 400

        update_response = (
            supabase.table("deliveries")
            .update({
                "status": new_status
            })
            .eq("id", database_delivery_id)
            .execute()
        )

        if not update_response.data:
            return jsonify({
                "success": False,
                "message": "Delivery not found"
            }), 404

        return jsonify({
            "success": True,
            "delivery_id": delivery_id,
            "status": new_status
        })

    except Exception as e:
        print("[ERROR] Status update:", e)
        return jsonify({
            "success": False,
            "message": "Could not update delivery status"
        }), 500


@app.route('/deliveries')
def deliveries():
    """Displays all delivery records."""

    delivery_data = load_deliveries()
    partners = load_delivery_partners()

    partner_map = {
        partner.get('partner_id'): partner
        for partner in partners
    }

    for delivery in delivery_data:
        partner_id = delivery.get('partner_id', '')
        delivery['partner'] = partner_map.get(partner_id, {})

    return render_template(
        'deliveries.html',
        deliveries=delivery_data
    )

@app.route('/delivery/<delivery_id>')
def delivery_details(delivery_id):
    """Displays details of a specific delivery."""

    delivery_data = load_deliveries()
    partners = load_delivery_partners()
    updates = load_location_updates()

    delivery = None

    for item in delivery_data:
        if item.get('delivery_id') == delivery_id:
            delivery = item
            break

    if delivery is None:
        return render_template(
            'index.html',
            error_message="Delivery not found."
        ), 404

    partner = None

    for item in partners:
        if item.get('partner_id') == delivery.get('partner_id'):
            partner = item
            break

    delivery_updates = []

    for update in updates:
        if update.get('delivery_id') == delivery_id:
            delivery_updates.append(update)

    return render_template(
        'delivery-details.html',
        delivery=delivery,
        partner=partner,
        location_updates=delivery_updates
    )

def search_closest_hospitals(blood_group, location_str="", user_lat=None, user_lon=None, units_needed=1):
    """
    Searches inventory for the requested blood group, joins with hospital details,
    calculates distance from user location, and sorts results from closest to farthest.
    """
    hospitals_map = load_hospitals()
    inventory_items = load_blood_inventory()

    if not hospitals_map or not inventory_items:
        return []

    target_group = blood_group.strip().upper()
    user_coords = resolve_location_coords(location_str, user_lat, user_lon)

    matching_results = []

    for item in inventory_items:
        item_group = item.get('blood_group', '').strip().upper()
        if item_group == target_group:
            status = item.get('status', '').strip()
            try:
                units = int(item.get('units', 0))
            except ValueError:
                units = 0

            # Only available hospitals where units > 0 and status is not 'Not Available'
            if units > 0 and status.lower() != 'not available':
                h_id = item.get('hospital_id', '').strip()
                hospital_info = hospitals_map.get(h_id)

                if hospital_info:
                    dist = haversine_distance(
                        user_coords[0], user_coords[1],
                        hospital_info.get('latitude'), hospital_info.get('longitude')
                    )
                    distance_display = f"{dist} km" if dist is not None else "Nearby"
                    distance_sort_key = dist if dist is not None else 999.0

                    result = {
                        'hospital_id': h_id,
                        'hospital_name': hospital_info['hospital_name'],
                        'address': hospital_info['address'],
                        'phone': hospital_info['phone'],
                        'latitude': hospital_info['latitude'],
                        'longitude': hospital_info['longitude'],
                        'blood_group': target_group,
                        'units': units,
                        'status': status,
                        'distance': distance_display,
                        'distance_num': distance_sort_key
                    }
                    matching_results.append(result)

    # Sort results by distance ascending (closest first)
    matching_results.sort(key=lambda x: (x['distance_num'], -x['units']))
    return matching_results


# -------------------------------------------------------------
# Flask Routes
# -------------------------------------------------------------

@app.route('/')
def home():
    """Step 0: Home page route."""
    return render_template('index.html', valid_blood_groups=VALID_BLOOD_GROUPS)

@app.route('/live-tracking')
def live_tracking():
    return render_template('live-tracking.html')

@app.route('/about')
def about():
    """About Us page route."""
    return render_template('about.html')


@app.route('/find-blood', methods=['GET', 'POST'])
def find_blood():
    """
    Step 1: Blood Requirement Form.
    Collects: Blood Group, Urgency Level, Location, Units required.
    """
    if request.method == 'POST':
        blood_group = request.form.get('blood_group', '').strip().upper()
        urgency = request.form.get('urgency', 'Urgent').strip()
        location = request.form.get('location', '').strip()
        units = request.form.get('units', '1').strip()
        date_needed = request.form.get('date_needed', '').strip()
        time_needed = request.form.get('time_needed', '').strip()
        user_lat = request.form.get('user_lat', '').strip()
        user_lon = request.form.get('user_lon', '').strip()

        if not blood_group or blood_group not in VALID_BLOOD_GROUPS:
            flash("Please select a valid blood group.", "danger")
            return render_template('find-blood.html', valid_blood_groups=VALID_BLOOD_GROUPS)

        # Pass requirements forward to Step 2: User Details
        return render_template(
            'login.html',
            blood_group=blood_group,
            urgency=urgency,
            location=location,
            units=units,
            date_needed=date_needed,
            time_needed=time_needed,
            user_lat=user_lat,
            user_lon=user_lon
        )

    return render_template('find-blood.html', valid_blood_groups=VALID_BLOOD_GROUPS)


@app.route('/user-details', methods=['GET', 'POST'])
def user_details():
    """
    Step 2: User Contact Details Form (Name, Phone, optional Email).
    When submitted, routes to the closest available hospitals.
    """
    if request.method == 'POST':
        blood_group = request.form.get('blood_group', '').strip().upper()
        urgency = request.form.get('urgency', 'Urgent').strip()
        location = request.form.get('location', '').strip()
        units = request.form.get('units', '1').strip()
        user_lat = request.form.get('user_lat', '').strip()
        user_lon = request.form.get('user_lon', '').strip()

        name = request.form.get('name', '').strip()
        phone = request.form.get('phone', '').strip()
        email = request.form.get('email', '').strip()

        # If name or phone are provided, proceed to closest hospitals
        if name and phone:
            return show_closest_hospitals(
                blood_group=blood_group,
                urgency=urgency,
                location=location,
                units=units,
                name=name,
                phone=phone,
                email=email,
                user_lat=user_lat,
                user_lon=user_lon
            )

        # Otherwise render form asking for details
        return render_template(
            'login.html',
            blood_group=blood_group,
            urgency=urgency,
            location=location,
            units=units,
            user_lat=user_lat,
            user_lon=user_lon
        )

    # GET request fallback
    return render_template('login.html', valid_blood_groups=VALID_BLOOD_GROUPS)


@app.route('/login', methods=['GET', 'POST'])
def login():
    """Alias route for the user details / login step."""
    return user_details()


def show_closest_hospitals(blood_group, urgency, location, units, name, phone, email, user_lat=None, user_lon=None):
    """
    Step 3: Searches and displays closest hospitals with required availability.
    """
    try:
        units_needed = int(units)
    except ValueError:
        units_needed = 1

    hospitals = search_closest_hospitals(
        blood_group=blood_group,
        location_str=location,
        user_lat=user_lat,
        user_lon=user_lon,
        units_needed=units_needed
    )

    return render_template(
        'availability.html',
        blood_group=blood_group,
        urgency=urgency,
        location=location or "Panvel",
        units=units,
        patient_name=name,
        contact_number=phone,
        email=email,
        hospitals=hospitals,
        total_found=len(hospitals),
        valid_blood_groups=VALID_BLOOD_GROUPS
    )


@app.route('/availability', methods=['GET', 'POST'])
def availability():
    """
    Direct route to availability page.
    Supports both GET search and POST from user contact details.
    """
    if request.method == 'POST':
        return user_details()

    # GET request - direct search
    blood_group = request.args.get('blood_group', '').strip().upper()
    location = request.args.get('location', '').strip()
    urgency = request.args.get('urgency', 'Urgent').strip()
    units = request.args.get('units', '1').strip()
    name = request.args.get('name', '').strip()
    phone = request.args.get('phone', '').strip()
    email = request.args.get('email', '').strip()

    error_message = None
    results = []

    if not blood_group:
        error_message = "Please select a blood group to check availability."
    elif blood_group not in VALID_BLOOD_GROUPS:
        error_message = f"Invalid blood group '{blood_group}'."
    else:
        results = search_closest_hospitals(blood_group, location)

    return render_template(
        'availability.html',
        blood_group=blood_group,
        location=location or "Panvel",
        urgency=urgency,
        units=units,
        patient_name=name,
        contact_number=phone,
        email=email,
        hospitals=results,
        total_found=len(results),
        error_message=error_message,
        valid_blood_groups=VALID_BLOOD_GROUPS
    )


@app.route('/request-blood', methods=['POST'])
def request_blood():

    hospital_id = request.form.get('hospital_id', '').strip()
    blood_group = request.form.get('blood_group', '').strip().upper()
    patient_name = request.form.get('name', '').strip()
    contact_number = request.form.get('phone', '').strip()
    email = request.form.get('email', '').strip()
    units_needed = request.form.get('units', '1').strip()
    urgency = request.form.get('urgency', 'Urgent').strip()
    location = request.form.get('location', '').strip()
    distance = request.form.get('distance', '').strip()

    try:
        units_needed_int = int(units_needed)
    except ValueError:
        units_needed_int = 1

    hospitals_map = load_hospitals()
    hospital_info = hospitals_map.get(hospital_id, {})

    hospital_name = hospital_info.get(
        'hospital_name',
        'Selected Hospital'
    )

    hospital_latitude = hospital_info.get('latitude')
    hospital_longitude = hospital_info.get('longitude')

    delivery_id = None
    assigned_partner = None

    # Find closest available partner
    if hospital_latitude is not None and hospital_longitude is not None:
        hospital_latitude = float(hospital_latitude)
        hospital_longitude = float(hospital_longitude)

        assigned_partner = find_closest_delivery_partner(
            hospital_latitude,
            hospital_longitude
        )

        print("[DELIVERY] Closest partner:", assigned_partner)

    # Create delivery
    if assigned_partner:
        delivery_response = (
            supabase
            .table("deliveries")
            .insert({
                "partner_id": assigned_partner["id"],
                "customer_name": patient_name,
                "customer_phone": contact_number,
                "blood_group": blood_group,
                "hospital_name": hospital_name,
                "destination": hospital_info.get("address", ""),
                "destination_latitude": hospital_latitude,
                "destination_longitude": hospital_longitude,
                "status": "Assigned",
                "eta_minutes": 0
            })
            .execute()
        )

        if delivery_response.data:
            delivery = delivery_response.data[0]
            delivery_id = delivery["id"]

            supabase.table("delivery_partners").update({
                "availability_status": "Busy"
            }).eq("id", assigned_partner["id"]).execute()

    # Thank-you page
    return render_template(
        'thankyou.html',
        success=True,
        patient_name=patient_name,
        contact_number=contact_number,
        email=email,
        blood_group=blood_group,
        hospital_name=hospital_name,
        hospital_address=hospital_info.get('address', ''),
        hospital_phone=hospital_info.get('phone', ''),
        units=units_needed,
        urgency=urgency,
        location=location,
        distance=distance,
        delivery_id=f"D{delivery_id:03d}" if delivery_id else None,
        partner_name=(
            assigned_partner["partner_name"]
            if assigned_partner else None
        ),
        partner_phone=(
            assigned_partner["phone"]
            if assigned_partner else None
        ),
        partner_vehicle=(
            assigned_partner["vehicle_type"]
            if assigned_partner else None
        ),
        partner_distance=(
            assigned_partner["distance_km"]
            if assigned_partner else None
        )
    )

@app.route('/thankyou')
def thankyou():
    """Thank you confirmation page."""
    return render_template('thankyou.html')


@app.errorhandler(404)
def page_not_found(e):
    return render_template('index.html', error_message="Page not found. Redirected to Home."), 404


@app.errorhandler(500)
def internal_server_error(e):
    return render_template('index.html', error_message="An internal server error occurred."), 500

if __name__ == "__main__":
    print("==================================================")
    print("  Starting BloodLink Flask Web Application...")
    print("  Open your browser at: http://127.0.0.1:5001/")
    print("==================================================")
    app.run(debug=True, port=5001)
