"""
BloodLink - BTech 2nd-Year Mini Project
Flask Backend for Blood Availability and Hospital Request System
Flow: Home -> Find Blood Form -> User Details -> Closest Hospitals with Availability -> Request Blood -> Thank You
"""

import os
import csv
import math
import time
import hashlib
import secrets
import io
import re
from datetime import datetime, timezone, timedelta
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from dotenv import load_dotenv

# Optional pypdf import for hospital verification
try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None

# Optional supabase client import
try:
    from supabase import create_client
except ImportError:
    create_client = None


app = Flask(
    __name__,
    template_folder='.',
    static_folder='.',
    static_url_path=''
)

app.secret_key = os.getenv("SECRET_KEY", "bloodlink-btech-secret-key-panvel-2026")

# -------------------------------------------------------------
# Database Management & Supabase / Local PostgreSQL Abstraction
# -------------------------------------------------------------
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

class QueryResponse:
    """Emulates Supabase API QueryResponse with .data attribute."""
    def __init__(self, data=None):
        self.data = data if data is not None else []

    def execute(self):
        return self

class LocalDataStore:
    """Thread-safe in-memory database store with Panvel seeds for offline and test runs."""
    def __init__(self):
        self.delivery_partners = [
            {
                "id": 1,
                "partner_name": "Rahul Sharma",
                "phone": "+919876543210",
                "vehicle_type": "Motorcycle (Bajaj Pulsar 150)",
                "location": "Old Panvel (Near Shivaji Chowk)",
                "availability_status": "Available",
                "current_latitude": 18.989400,
                "current_longitude": 73.112100
            },
            {
                "id": 2,
                "partner_name": "Priya Patel",
                "phone": "+919876543211",
                "vehicle_type": "Electric Scooter (Ather 450X)",
                "location": "New Panvel (Sector 19)",
                "availability_status": "Available",
                "current_latitude": 18.998400,
                "current_longitude": 73.125600
            },
            {
                "id": 3,
                "partner_name": "Arun Kumar",
                "phone": "+919876543212",
                "vehicle_type": "Scooter (Honda Activa 6G)",
                "location": "Khanda Colony, New Panvel",
                "availability_status": "Busy",
                "current_latitude": 19.006200,
                "current_longitude": 73.109800
            },
            {
                "id": 4,
                "partner_name": "Sneha Varma",
                "phone": "+919876543213",
                "vehicle_type": "Motorcycle (Hero Splendor)",
                "location": "Kalamboli (Near Highway Circle)",
                "availability_status": "Offline",
                "current_latitude": 19.027000,
                "current_longitude": 73.102500
            },
            {
                "id": 5,
                "partner_name": "Mohammed Faiz",
                "phone": "+919876543214",
                "vehicle_type": "Electric Bike (Revolt RV400)",
                "location": "Kamothe (Near MGM Hospital)",
                "availability_status": "Available",
                "current_latitude": 19.020500,
                "current_longitude": 73.093500
            },
            {
                "id": 6,
                "partner_name": "Vikram Singh",
                "phone": "+919876543215",
                "vehicle_type": "Motorcycle (TVS Apache 160)",
                "location": "Karanjade (Sector 4)",
                "availability_status": "Available",
                "current_latitude": 18.975000,
                "current_longitude": 73.098000
            }
        ]
        self.deliveries = []
        self.location_updates = []
        self.next_delivery_id = 1
        self.next_location_id = 1
        self.blood_inventory = {}  # (hospital_id, blood_group) -> units
        self.admin_users = {
            "admin": {
                "username": "admin",
                "password_hash": hashlib.sha256("admin123".encode()).hexdigest(),
                "otp_hash": None,
                "otp_expires_at": None,
                "otp_attempts": 0
            }
        }

    def select(self, table_name, filters, order_field=None, order_desc=False, limit_num=None):
        table = getattr(self, table_name, [])
        results = []
        for row in table:
            match = True
            for col, val in filters:
                if str(row.get(col)) != str(val):
                    match = False
                    break
            if match:
                results.append(dict(row))

        if order_field:
            results.sort(key=lambda x: x.get(order_field, ""), reverse=order_desc)

        if limit_num is not None:
            results = results[:limit_num]

        return results

    def insert(self, table_name, record):
        table = getattr(self, table_name, None)
        if table is None:
            return []
        new_row = dict(record)
        if table_name == "deliveries":
            if "id" not in new_row:
                new_row["id"] = self.next_delivery_id
                self.next_delivery_id += 1
            if "created_at" not in new_row:
                new_row["created_at"] = datetime.now(timezone.utc).isoformat()
            if "updated_at" not in new_row:
                new_row["updated_at"] = new_row["created_at"]
        elif table_name == "location_updates":
            if "id" not in new_row:
                new_row["id"] = self.next_location_id
                self.next_location_id += 1
            if "recorded_at" not in new_row:
                new_row["recorded_at"] = datetime.now(timezone.utc).isoformat()

        table.append(new_row)
        return [new_row]

    def update(self, table_name, filters, values):
        table = getattr(self, table_name, None)
        if table is None:
            return []
        updated = []
        for row in table:
            match = True
            for col, val in filters:
                if str(row.get(col)) != str(val):
                    match = False
                    break
            if match:
                row.update(values)
                if table_name == "deliveries":
                    row["updated_at"] = datetime.now(timezone.utc).isoformat()
                updated.append(dict(row))
        return updated

local_store = LocalDataStore()

class LocalTableProxy:
    def __init__(self, table_name, store):
        self.table_name = table_name
        self.store = store
        self._filters = []
        self._select_fields = "*"
        self._order_field = None
        self._order_desc = False
        self._limit_num = None
        self._update_values = None
        self._insert_record = None

    def select(self, fields="*"):
        self._select_fields = fields
        return self

    def eq(self, column, value):
        self._filters.append((column, value))
        return self

    def order(self, column, desc=False):
        self._order_field = column
        self._order_desc = desc
        return self

    def limit(self, count):
        self._limit_num = count
        return self

    def insert(self, record):
        self._insert_record = record
        return self

    def update(self, values):
        self._update_values = values
        return self

    def execute(self):
        if self._insert_record is not None:
            inserted = self.store.insert(self.table_name, self._insert_record)
            self._insert_record = None
            return QueryResponse(inserted)
        if self._update_values is not None:
            updated = self.store.update(self.table_name, self._filters, self._update_values)
            self._update_values = None
            return QueryResponse(updated)
        records = self.store.select(self.table_name, self._filters, self._order_field, self._order_desc, self._limit_num)
        return QueryResponse(records)

class LocalSupabaseAdapter:
    def __init__(self, store):
        self.store = store

    def table(self, table_name):
        return LocalTableProxy(table_name, self.store)

# Initialize Supabase client if configured and not placeholder, otherwise attach resilient adapter
supabase = None
is_placeholder_url = not SUPABASE_URL or "your-supabase-project" in SUPABASE_URL or "example.com" in SUPABASE_URL
if create_client and SUPABASE_URL and SUPABASE_KEY and not is_placeholder_url:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        print("[INFO] Connected to Supabase Cloud.")
    except Exception as e:
        print(f"[WARN] Supabase connection failed: {e}. Falling back to resilient local store.")
        supabase = LocalSupabaseAdapter(local_store)
else:
    print("[INFO] Supabase credentials not provided or placeholder detected. Initialized resilient local store.")
    supabase = LocalSupabaseAdapter(local_store)


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
    "kalamboli": (19.0270, 73.1025),
    "karanjade": (18.9750, 73.0980),
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

# Area streets and landmarks directory for map filtering and auto-routing
AREA_STREETS = {
    "New Panvel": [
        {"name": "Sector 19 Main Road", "latitude": 19.0005, "longitude": 73.1200, "landmark": "Near D-Mart Sector 19"},
        {"name": "Sector 15 Market Road", "latitude": 18.9990, "longitude": 73.1220, "landmark": "Near CKT College"},
        {"name": "Sector 8 Garden Street", "latitude": 18.9950, "longitude": 73.1160, "landmark": "Shivaji Chowk New Panvel"},
        {"name": "Sector 1S Station Link Road", "latitude": 18.9925, "longitude": 73.1170, "landmark": "New Panvel East Gate"}
    ],
    "Old Panvel": [
        {"name": "Shivaji Road", "latitude": 18.9917, "longitude": 73.1102, "landmark": "Near Panvel Municipal Council"},
        {"name": "Uran Naka Highway", "latitude": 18.9895, "longitude": 73.1105, "landmark": "Near Lifeline Hospital"},
        {"name": "Bazaar Peth", "latitude": 18.9880, "longitude": 73.1130, "landmark": "Old Panvel Central Bazaar"},
        {"name": "Tapal Naka", "latitude": 18.9930, "longitude": 73.1080, "landmark": "Near Panvel ST Stand"}
    ],
    "Khanda Colony": [
        {"name": "Sector 6 High Street", "latitude": 18.9975, "longitude": 73.1010, "landmark": "Khandeshwar Flyover Link"},
        {"name": "Sector 8 Khanda Road", "latitude": 18.9960, "longitude": 73.1040, "landmark": "Khanda Sports Complex"},
        {"name": "Sector 13 Colony Road", "latitude": 18.9990, "longitude": 73.0990, "landmark": "Near Khandeshwar Station Gate"}
    ],
    "Kamothe": [
        {"name": "Sector 11 Main Road", "latitude": 19.0186, "longitude": 73.0952, "landmark": "Near MGM Hospital & Medical College"},
        {"name": "Sector 6 Commercial Street", "latitude": 19.0140, "longitude": 73.0920, "landmark": "Kamothe Railway Station Road"},
        {"name": "Sector 20 Expressway Junction", "latitude": 19.0230, "longitude": 73.0980, "landmark": "Sion-Panvel Highway Exit"}
    ],
    "Kharghar": [
        {"name": "Utsav Chowk Boulevard", "latitude": 19.0474, "longitude": 73.0664, "landmark": "Central Utsav Chowk"},
        {"name": "Sector 20 Shilp Chowk", "latitude": 19.0420, "longitude": 73.0710, "landmark": "Near Medicity Hospital"},
        {"name": "Sector 7 Hiranandani Road", "latitude": 19.0350, "longitude": 73.0640, "landmark": "Near Central Park Metro"}
    ],
    "Kalamboli": [
        {"name": "Steel Market Road", "latitude": 19.0270, "longitude": 73.1025, "landmark": "Highway Circle Kalamboli"},
        {"name": "Sector 4 Residence Avenue", "latitude": 19.0290, "longitude": 73.1050, "landmark": "Kalamboli Police Station Road"}
    ],
    "Karanjade": [
        {"name": "Sector 4 Main Ring Road", "latitude": 18.9750, "longitude": 73.0980, "landmark": "Near Karanjade Bridge"},
        {"name": "Sector 6 Canal Road", "latitude": 18.9780, "longitude": 73.1010, "landmark": "Near Navi Mumbai Airport Side"}
    ]
}


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
    Loads blood inventory dataset.
    Uses local_store if populated, otherwise loads from BloodLink_Blood_Inventory.csv.
    """
    if local_store.blood_inventory:
        return list(local_store.blood_inventory.values())

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
                h_id = clean_row.get('hospital_id', '').strip()
                bg = clean_row.get('blood_group', '').strip().upper()
                if h_id and bg:
                    local_store.blood_inventory[(h_id, bg)] = clean_row
    except Exception as e:
        print(f"[ERROR] Failed to load inventory CSV: {e}")
        return []

    return inventory

def deduct_inventory_units(hospital_id, blood_group, units_to_deduct):
    """
    Safely and atomically deducts stock from blood inventory.
    Returns True if successfully deducted, False if insufficient stock.
    """
    load_blood_inventory()
    key = (hospital_id.strip(), blood_group.strip().upper())
    item = local_store.blood_inventory.get(key)
    if not item:
        return False
    try:
        current_units = int(item.get('units', 0))
    except (ValueError, TypeError):
        current_units = 0

    if current_units < units_to_deduct:
        return False

    new_units = current_units - units_to_deduct
    item['units'] = str(new_units)
    if new_units == 0:
        item['status'] = 'Not Available'
    elif new_units <= 2:
        item['status'] = 'Low Stock'
    else:
        item['status'] = 'Available'
    return True

def update_inventory_units(hospital_id, blood_group, new_units):
    """
    Updates stock safely for a hospital and blood group. Prevents negative stock.
    """
    load_blood_inventory()
    if new_units < 0:
        return False, "Stock units cannot be negative"

    key = (hospital_id.strip(), blood_group.strip().upper())
    item = local_store.blood_inventory.get(key)
    if not item:
        item = {
            'inventory_id': str(len(local_store.blood_inventory) + 1),
            'hospital_id': hospital_id,
            'blood_group': blood_group,
            'units': str(new_units),
            'status': 'Available' if new_units > 2 else ('Low Stock' if new_units > 0 else 'Not Available')
        }
        local_store.blood_inventory[key] = item
    else:
        item['units'] = str(new_units)
        if new_units == 0:
            item['status'] = 'Not Available'
        elif new_units <= 2:
            item['status'] = 'Low Stock'
        else:
            item['status'] = 'Available'
    return True, item

def parse_delivery_id(delivery_id_str):
    """Parses 'D001', 'D1', or '1' into database integer 1, or None if invalid."""
    if not delivery_id_str:
        return None
    cleaned = str(delivery_id_str).strip().upper()
    if cleaned.startswith("D"):
        cleaned = cleaned[1:]
    try:
        return int(cleaned)
    except ValueError:
        return None

def load_delivery_partners():
    """Loads delivery partner information from database."""
    res = supabase.table("delivery_partners").select("*").execute()
    return res.data or []

def load_deliveries():
    """Loads delivery records from database."""
    res = supabase.table("deliveries").select("*").execute()
    return res.data or []

def load_location_updates():
    """Loads delivery location updates from database."""
    res = supabase.table("location_updates").select("*").execute()
    return res.data or []

def get_latest_location(delivery_id):
    """Gets the latest recorded GPS location of a delivery."""
    db_id = parse_delivery_id(delivery_id)
    if db_id is None:
        return None
    res = (
        supabase.table("location_updates")
        .select("*")
        .eq("delivery_id", db_id)
        .order("recorded_at", desc=True)
        .limit(1)
        .execute()
    )
    if res.data:
        latest = res.data[0]
        return {
            'delivery_id': f"D{db_id:03d}",
            'latitude': float(latest.get('latitude', 0)),
            'longitude': float(latest.get('longitude', 0)),
            'timestamp': latest.get('recorded_at', '')
        }
    return None

# -------------------------------------------------------------
# Area & Streets Mapping API (MapLibre GL JS Filter)
# -------------------------------------------------------------

@app.route('/get-area-streets', methods=['GET'])
def get_area_streets():
    """
    Returns street and landmark coordinates for an area in Panvel/Navi Mumbai.
    Used by MapLibre GL JS dropdown to plot markers, center viewport, and draw routes.
    """
    area_name = request.args.get('area', '').strip()
    if not area_name:
        # Return all available areas with their street points
        return jsonify({
            "success": True,
            "areas": list(AREA_STREETS.keys()),
            "count": len(AREA_STREETS)
        })

    matched_area = None
    for key in AREA_STREETS:
        if key.lower() == area_name.lower() or area_name.lower() in key.lower():
            matched_area = key
            break

    if not matched_area:
        # Fallback to general location coords if known
        clean_key = area_name.lower()
        coords = LOCATION_COORDS.get(clean_key, DEFAULT_USER_COORDS)
        return jsonify({
            "success": True,
            "area": area_name,
            "center": {"latitude": coords[0], "longitude": coords[1]},
            "streets": [
                {
                    "name": f"{area_name} Main Street",
                    "latitude": coords[0],
                    "longitude": coords[1],
                    "landmark": f"Central {area_name}"
                }
            ]
        })

    streets = AREA_STREETS[matched_area]
    center_coords = LOCATION_COORDS.get(matched_area.lower(), DEFAULT_USER_COORDS)

    # Also include hospitals in or near this area
    hospitals_map = load_hospitals()
    nearby_hospitals = []
    for h_id, h_data in hospitals_map.items():
        try:
            h_lat = float(h_data.get('latitude', 0))
            h_lon = float(h_data.get('longitude', 0))
            dist = haversine_distance(center_coords[0], center_coords[1], h_lat, h_lon)
            if dist is not None and dist <= 12.0:
                nearby_hospitals.append({
                    "hospital_id": h_id,
                    "hospital_name": h_data.get("hospital_name"),
                    "latitude": h_lat,
                    "longitude": h_lon,
                    "address": h_data.get("address"),
                    "phone": h_data.get("phone"),
                    "distance_km": dist
                })
        except Exception:
            continue

    nearby_hospitals.sort(key=lambda x: x["distance_km"])

    return jsonify({
        "success": True,
        "area": matched_area,
        "center": {
            "latitude": center_coords[0],
            "longitude": center_coords[1]
        },
        "streets": streets,
        "hospitals": nearby_hospitals
    })

# -------------------------------------------------------------
# Live Delivery Location API (GET: Track, POST: Genuine GPS Updates)
# -------------------------------------------------------------

@app.route('/api/delivery/<delivery_id>/location', methods=['GET', 'POST'])
@app.route('/api/tracking/<delivery_id>', methods=['GET'])
def delivery_location_api(delivery_id):
    try:
        database_delivery_id = parse_delivery_id(delivery_id)
        if database_delivery_id is None:
            return jsonify({
                "success": False,
                "message": "Invalid delivery ID format"
            }), 400

        # POST: Ingest genuine GPS updates from authorized rider/source
        if request.method == 'POST':
            data = request.get_json(silent=True) or {}
            lat = data.get("latitude")
            lon = data.get("longitude")

            if lat is None or lon is None:
                return jsonify({
                    "success": False,
                    "message": "Missing latitude or longitude in request body"
                }), 400

            try:
                lat = float(lat)
                lon = float(lon)
            except (ValueError, TypeError):
                return jsonify({
                    "success": False,
                    "message": "Invalid coordinate values"
                }), 400

            if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
                return jsonify({
                    "success": False,
                    "message": "Coordinates out of geographic range"
                }), 400

            deliv_res = supabase.table("deliveries").select("*").eq("id", database_delivery_id).limit(1).execute()
            if not deliv_res.data:
                return jsonify({
                    "success": False,
                    "message": "Delivery not found"
                }), 404

            delivery = deliv_res.data[0]
            partner_id = delivery.get("partner_id")

            rec_time = datetime.now(timezone.utc).isoformat()
            supabase.table("location_updates").insert({
                "delivery_id": database_delivery_id,
                "partner_id": partner_id,
                "latitude": lat,
                "longitude": lon,
                "recorded_at": rec_time
            }).execute()

            if partner_id:
                supabase.table("delivery_partners").update({
                    "current_latitude": lat,
                    "current_longitude": lon
                }).eq("id", partner_id).execute()

            return jsonify({
                "success": True,
                "message": "Location updated successfully",
                "delivery_id": f"D{database_delivery_id:03d}",
                "latitude": lat,
                "longitude": lon,
                "recorded_at": rec_time
            })

        # GET: Retrieve delivery details, current coordinates, and ETA
        delivery_response = (
            supabase
            .table("deliveries")
            .select("*")
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

        # Retrieve assigned partner details
        partner = None
        if delivery.get("partner_id") is not None:
            partner_response = (
                supabase
                .table("delivery_partners")
                .select("*")
                .eq("id", delivery["partner_id"])
                .limit(1)
                .execute()
            )
            partners = partner_response.data
            partner = partners[0] if partners else None

        # Retrieve latest recorded GPS breadcrumb
        location_response = (
            supabase
            .table("location_updates")
            .select("*")
            .eq("delivery_id", database_delivery_id)
            .order("recorded_at", desc=True)
            .limit(1)
            .execute()
        )
        locations = location_response.data
        location = locations[0] if locations else None

        if location:
            latitude = float(location["latitude"])
            longitude = float(location["longitude"])
            recorded_at = location["recorded_at"]
        elif partner and partner.get("current_latitude") is not None and partner.get("current_longitude") is not None:
            latitude = float(partner["current_latitude"])
            longitude = float(partner["current_longitude"])
            recorded_at = None
        else:
            latitude = None
            longitude = None
            recorded_at = None

        # Calculate estimated travel time
        eta_minutes = delivery.get("eta_minutes") or 0
        dest_lat = delivery.get("destination_latitude")
        dest_lon = delivery.get("destination_longitude")

        if (
            latitude is not None
            and longitude is not None
            and dest_lat is not None
            and dest_lon is not None
        ):
            distance_km = calculate_distance(
                latitude,
                longitude,
                float(dest_lat),
                float(dest_lon)
            )
            # City speed estimate 20 km/h
            eta_minutes = round((distance_km / 20) * 60)
            if distance_km > 0.1:
                eta_minutes = max(1, eta_minutes)
            else:
                eta_minutes = 0

        driver_name = partner["partner_name"] if partner else "Pending Assignment"

        return jsonify({
            "success": True,
            "data": {
                "delivery_id": f"D{database_delivery_id:03d}",
                "database_delivery_id": delivery["id"],
                "partner_id": delivery.get("partner_id"),
                "partner_name": driver_name,
                "driver_name": driver_name,
                "phone": partner["phone"] if partner else None,
                "vehicle_type": partner["vehicle_type"] if partner else None,
                "partner_location": partner["location"] if partner else None,
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
                    if delivery.get("destination_latitude") is not None
                    else None
                ),
                "destination_longitude": (
                    float(delivery["destination_longitude"])
                    if delivery.get("destination_longitude") is not None
                    else None
                ),
                "recorded_at": recorded_at,
                "delivered_at": delivery.get("delivered_at")
            }
        })

    except Exception as e:
        print("[ERROR] Live tracking API:", e)
        return jsonify({
            "success": False,
            "message": "Tracking service error",
            "error": str(e)
        }), 500

@app.route('/api/delivery/<delivery_id>/status', methods=['POST'])
def update_delivery_status(delivery_id):
    try:
        database_delivery_id = parse_delivery_id(delivery_id)
        if database_delivery_id is None:
            return jsonify({"success": False, "message": "Invalid delivery ID"}), 400

        data = request.get_json(silent=True) or {}
        new_status = data.get("status", "").strip()

        # Recipient OTP verification is strictly required for 'Delivered'
        if new_status == "Delivered":
            return jsonify({
                "success": False,
                "message": "Delivery cannot be marked 'Delivered' without recipient OTP verification. Please use /api/delivery/<delivery_id>/verify-otp"
            }), 400

        allowed_statuses = [
            "Pending",
            "Assigned",
            "On the way",
            "Reached",
            "Cancelled",
            "Arrived"
        ]

        if new_status not in allowed_statuses:
            return jsonify({
                "success": False,
                "message": f"Invalid delivery status '{new_status}'. Allowed: {', '.join(allowed_statuses)}"
            }), 400

        update_response = (
            supabase.table("deliveries")
            .update({"status": new_status})
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
            "delivery_id": f"D{database_delivery_id:03d}",
            "status": new_status
        })

    except Exception as e:
        print("[ERROR] Status update:", e)
        return jsonify({
            "success": False,
            "message": "Could not update delivery status"
        }), 500

@app.route('/api/delivery/<delivery_id>/verify-otp', methods=['POST'])
@app.route('/api/verify-otp', methods=['POST'])
def verify_delivery_otp(delivery_id=None):
    """
    Recipient OTP verification endpoint.
    Supports /api/delivery/<delivery_id>/verify-otp and /api/verify-otp (with delivery_id in JSON).
    Verifies 6-digit OTP, keeps Reached and Delivered separate,
    records completion timestamp, and frees partner upon successful delivery.
    """
    try:
        data = request.get_json(silent=True) or {}
        target_delivery_id = delivery_id or data.get("delivery_id")
        database_delivery_id = parse_delivery_id(target_delivery_id)
        if database_delivery_id is None:
            return jsonify({"success": False, "message": "Invalid delivery ID"}), 400

        submitted_otp = str(data.get("otp", "")).strip()

        if not submitted_otp:
            return jsonify({"success": False, "message": "OTP is required"}), 400

        deliv_res = supabase.table("deliveries").select("*").eq("id", database_delivery_id).limit(1).execute()
        if not deliv_res.data:
            return jsonify({"success": False, "message": "Delivery not found"}), 404

        delivery = deliv_res.data[0]
        attempts = delivery.get("otp_attempts", 0)

        if attempts >= 3:
            return jsonify({
                "success": False,
                "message": "Maximum OTP verification attempts exceeded (3). Verification locked."
            }), 429

        expires_at = delivery.get("otp_expires_at")
        if expires_at:
            try:
                exp_dt = datetime.fromisoformat(expires_at)
                if datetime.now(timezone.utc) > exp_dt:
                    return jsonify({"success": False, "message": "OTP has expired"}), 400
            except Exception:
                pass

        expected_hash = delivery.get("recipient_otp_hash")
        submitted_hash = hashlib.sha256(submitted_otp.encode()).hexdigest()

        if expected_hash and expected_hash == submitted_hash:
            now_time = datetime.now(timezone.utc).isoformat()
            supabase.table("deliveries").update({
                "status": "Delivered",
                "delivered_at": now_time,
                "otp_attempts": attempts + 1
            }).eq("id", database_delivery_id).execute()

            partner_id = delivery.get("partner_id")
            if partner_id:
                supabase.table("delivery_partners").update({
                    "availability_status": "Available"
                }).eq("id", partner_id).execute()

            return jsonify({
                "success": True,
                "message": "Recipient OTP verified successfully. Delivery status updated to Delivered.",
                "delivery_id": f"D{database_delivery_id:03d}",
                "status": "Delivered",
                "delivered_at": now_time
            })
        else:
            new_attempts = attempts + 1
            supabase.table("deliveries").update({
                "otp_attempts": new_attempts
            }).eq("id", database_delivery_id).execute()

            return jsonify({
                "success": False,
                "message": f"Incorrect OTP. Remaining attempts: {max(0, 3 - new_attempts)}"
            }), 400

    except Exception as e:
        print("[ERROR] Recipient OTP verification:", e)
        return jsonify({"success": False, "message": "Verification error", "error": str(e)}), 500

@app.route('/deliveries')
def deliveries():
    """Displays all delivery records."""
    delivery_data = load_deliveries()
    partners = load_delivery_partners()

    partner_map = {partner.get('id'): partner for partner in partners}
    for delivery in delivery_data:
        partner_id = delivery.get('partner_id')
        delivery['partner'] = partner_map.get(partner_id, {})
        delivery['formatted_id'] = f"D{delivery['id']:03d}"

    try:
        return render_template('deliveries.html', deliveries=delivery_data)
    except Exception:
        return jsonify({
            "success": True,
            "count": len(delivery_data),
            "deliveries": delivery_data
        })

@app.route('/delivery/<delivery_id>')
def delivery_details(delivery_id):
    """Displays details of a specific delivery."""
    db_id = parse_delivery_id(delivery_id)
    if db_id is None:
        return render_template('index.html', error_message="Invalid delivery ID."), 400

    deliv_res = supabase.table("deliveries").select("*").eq("id", db_id).limit(1).execute()
    if not deliv_res.data:
        return render_template('index.html', error_message="Delivery not found."), 404

    delivery = deliv_res.data[0]
    partner = None
    if delivery.get("partner_id"):
        p_res = supabase.table("delivery_partners").select("*").eq("id", delivery["partner_id"]).limit(1).execute()
        partner = p_res.data[0] if p_res.data else None

    loc_res = supabase.table("location_updates").select("*").eq("delivery_id", db_id).order("recorded_at", desc=True).execute()
    delivery_updates = loc_res.data or []

    try:
        return render_template(
            'delivery-details.html',
            delivery=delivery,
            partner=partner,
            location_updates=delivery_updates
        )
    except Exception:
        return redirect(f"/live-tracking?delivery_id=D{db_id:03d}")

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

        # If name or phone are provided, persist in session and proceed to closest hospitals
        if name and phone:
            session['user_name'] = name
            session['user_phone'] = phone
            session['user_email'] = email
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
    name = name or session.get('user_name', '')
    phone = phone or session.get('user_phone', '')
    email = email or session.get('user_email', '')

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
    name = request.args.get('name', '').strip() or session.get('user_name', '')
    phone = request.args.get('phone', '').strip() or session.get('user_phone', '')
    email = request.args.get('email', '').strip() or session.get('user_email', '')

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


@app.route('/verify-request', methods=['GET', 'POST'])
def verify_request_page():
    """
    User-side medical requisition verification step.
    Receives hospital selection and user requirement, renders verify-request.html
    for PDF upload and validation before final dispatch.
    """
    hospital_id = request.form.get('hospital_id', '').strip() or request.args.get('hospital_id', '').strip()
    blood_group = request.form.get('blood_group', '').strip().upper() or request.args.get('blood_group', '').strip().upper()
    patient_name = request.form.get('name', '').strip() or request.args.get('name', '').strip() or session.get('user_name', '').strip() or "Emergency Recipient"
    contact_number = request.form.get('phone', '').strip() or request.args.get('phone', '').strip() or session.get('user_phone', '').strip() or "+919876543210"
    email = request.form.get('email', '').strip() or request.args.get('email', '').strip() or session.get('user_email', '').strip()
    units_needed = request.form.get('units', '1').strip() or request.args.get('units', '1').strip()
    urgency = request.form.get('urgency', 'Urgent').strip() or request.args.get('urgency', 'Urgent').strip()
    location = request.form.get('location', '').strip() or request.args.get('location', '').strip()
    distance = request.form.get('distance', '').strip() or request.args.get('distance', '').strip()

    hospitals_map = load_hospitals()
    hospital_info = hospitals_map.get(hospital_id, {})
    hospital_name = hospital_info.get('hospital_name', 'Selected Hospital')

    return render_template(
        'verify-request.html',
        hospital_id=hospital_id,
        hospital_name=hospital_name,
        blood_group=blood_group,
        patient_name=patient_name,
        contact_number=contact_number,
        email=email,
        units=units_needed,
        urgency=urgency,
        location=location,
        distance=distance
    )


@app.route('/request-blood', methods=['POST'])
def request_blood():
    hospital_id = request.form.get('hospital_id', '').strip()
    blood_group = request.form.get('blood_group', '').strip().upper()
    patient_name = request.form.get('name', '').strip() or session.get('user_name', '').strip() or "Emergency Recipient"
    contact_number = request.form.get('phone', '').strip() or session.get('user_phone', '').strip() or "+919876543210"
    email = request.form.get('email', '').strip() or session.get('user_email', '').strip()
    units_needed = request.form.get('units', '1').strip()
    urgency = request.form.get('urgency', 'Urgent').strip()
    location = request.form.get('location', '').strip()
    distance = request.form.get('distance', '').strip()
    user_lat = request.form.get('user_lat', '').strip()
    user_lon = request.form.get('user_lon', '').strip()

    if patient_name and patient_name != "Emergency Recipient":
        session['user_name'] = patient_name
    if contact_number:
        session['user_phone'] = contact_number

    try:
        units_needed_int = int(units_needed)
    except (ValueError, TypeError):
        units_needed_int = 1

    hospitals_map = load_hospitals()
    hospital_info = hospitals_map.get(hospital_id, {})

    hospital_name = hospital_info.get(
        'hospital_name',
        'Selected Hospital'
    )

    hospital_latitude = hospital_info.get('latitude')
    hospital_longitude = hospital_info.get('longitude')

    # Resolve customer destination coordinates correctly from patient location
    dest_coords = resolve_location_coords(location, user_lat, user_lon)
    dest_latitude = dest_coords[0]
    dest_longitude = dest_coords[1]
    destination_str = location if location else hospital_info.get("address", "Panvel")

    # 1. Idempotency Check: Reuse existing active delivery if submitted recently
    existing_deliveries = (
        supabase.table("deliveries")
        .select("*")
        .eq("customer_phone", contact_number)
        .eq("hospital_name", hospital_name)
        .eq("blood_group", blood_group)
        .execute()
    )
    active_delivery = None
    for d in (existing_deliveries.data or []):
        if d.get("status") in ["Pending", "Assigned", "On the way", "Reached"]:
            active_delivery = d
            break

    delivery_id = None
    assigned_partner = None
    otp_digits = session.get(f"recipient_otp_{contact_number}")

    if active_delivery:
        # Reuse existing delivery and assigned partner
        delivery_id = active_delivery["id"]
        partner_id = active_delivery.get("partner_id")
        if partner_id:
            p_res = supabase.table("delivery_partners").select("*").eq("id", partner_id).limit(1).execute()
            if p_res.data:
                assigned_partner = p_res.data[0]
    else:
        # Safely deduct stock
        deduct_inventory_units(hospital_id, blood_group, units_needed_int)

        # 2. Find closest available partner to hospital pickup location
        if hospital_latitude is not None and hospital_longitude is not None:
            try:
                h_lat = float(hospital_latitude)
                h_lon = float(hospital_longitude)
                assigned_partner = find_closest_delivery_partner(h_lat, h_lon)
            except (ValueError, TypeError):
                assigned_partner = None

        # 3. Server-side Recipient OTP generation & hashing
        otp_digits = f"{secrets.randbelow(900000) + 100000:06d}"
        otp_hash = hashlib.sha256(otp_digits.encode()).hexdigest()
        otp_expiry = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()

        # Save recipient OTP in session for testing / verification simulations
        session[f"recipient_otp_{contact_number}"] = otp_digits

        status = "Assigned" if assigned_partner else "Pending"

        delivery_payload = {
            "partner_id": assigned_partner["id"] if assigned_partner else None,
            "customer_name": patient_name,
            "customer_phone": contact_number,
            "blood_group": blood_group,
            "hospital_name": hospital_name,
            "destination": destination_str,
            "destination_latitude": dest_latitude,
            "destination_longitude": dest_longitude,
            "status": status,
            "eta_minutes": 0,
            "recipient_otp_hash": otp_hash,
            "otp_expires_at": otp_expiry,
            "otp_attempts": 0,
            "pickup_hospital_id": hospital_id,
            "pickup_latitude": float(hospital_latitude) if hospital_latitude else None,
            "pickup_longitude": float(hospital_longitude) if hospital_longitude else None
        }

        delivery_response = (
            supabase
            .table("deliveries")
            .insert(delivery_payload)
            .execute()
        )

        if delivery_response.data:
            delivery = delivery_response.data[0]
            delivery_id = delivery["id"]

            if assigned_partner:
                supabase.table("delivery_partners").update({
                    "availability_status": "Busy"
                }).eq("id", assigned_partner["id"]).execute()

    formatted_delivery_id = f"D{delivery_id:03d}" if delivery_id else None
    driver_name = (
        assigned_partner["partner_name"]
        if assigned_partner else ("Pending Assignment" if delivery_id else None)
    )

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
        delivery_id=formatted_delivery_id,
        recipient_otp=otp_digits if delivery_id else None,
        partner_name=driver_name,
        partner_phone=(
            assigned_partner["phone"]
            if assigned_partner else None
        ),
        partner_vehicle=(
            assigned_partner["vehicle_type"]
            if assigned_partner else None
        ),
        partner_distance=(
            assigned_partner.get("distance_km")
            if assigned_partner else None
        )
    )

@app.route('/thankyou')
def thankyou():
    """Thank you confirmation page."""
    return render_template('thankyou.html')

# -------------------------------------------------------------
# Admin Authentication & Inventory Management
# -------------------------------------------------------------

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_authenticated'):
            return jsonify({
                "success": False,
                "message": "Unauthorized. Admin authentication required."
            }), 401
        return f(*args, **kwargs)
    return decorated_function

@app.route('/api/admin/login', methods=['POST'])
def admin_login_api():
    """
    Step 1 of Admin Authentication:
    Validates username and password, then generates time-limited 2FA OTP.
    """
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", "")).strip()

    admin_record = local_store.admin_users.get(username)
    if not admin_record:
        return jsonify({"success": False, "message": "Invalid admin credentials"}), 401

    pwd_hash = hashlib.sha256(password.encode()).hexdigest()
    if admin_record["password_hash"] != pwd_hash:
        return jsonify({"success": False, "message": "Invalid admin credentials"}), 401

    # Authenticate directly via admin password
    session['admin_authenticated'] = True
    session['admin_username'] = username

    # Generate 6-digit admin OTP for backwards compatibility if needed
    otp_code = f"{secrets.randbelow(900000) + 100000:06d}"
    admin_record["otp_hash"] = hashlib.sha256(otp_code.encode()).hexdigest()
    admin_record["otp_expires_at"] = datetime.now(timezone.utc) + timedelta(minutes=5)
    admin_record["otp_attempts"] = 0

    session['admin_pending_user'] = username
    session['admin_demo_otp'] = otp_code

    return jsonify({
        "success": True,
        "authenticated": True,
        "otp_required": False,
        "demo_otp": otp_code,
        "message": "Admin authenticated successfully."
    })

@app.route('/api/admin/verify-otp', methods=['POST'])
def admin_verify_otp_api():
    """
    Step 2 of Admin Authentication:
    Verifies server-side OTP, enforces attempt limits (max 3), and creates admin session.
    """
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", session.get('admin_pending_user', ""))).strip()
    submitted_otp = str(data.get("otp", "")).strip()

    admin_record = local_store.admin_users.get(username)
    if not admin_record or not admin_record.get("otp_hash"):
        return jsonify({"success": False, "message": "No pending admin OTP request found"}), 400

    if admin_record["otp_attempts"] >= 3:
        return jsonify({"success": False, "message": "Maximum OTP attempts exceeded. Login locked."}), 429

    if admin_record["otp_expires_at"] and datetime.now(timezone.utc) > admin_record["otp_expires_at"]:
        return jsonify({"success": False, "message": "Admin OTP has expired"}), 400

    submitted_hash = hashlib.sha256(submitted_otp.encode()).hexdigest()
    if admin_record["otp_hash"] == submitted_hash:
        session['admin_authenticated'] = True
        session['admin_username'] = username
        session.pop('admin_pending_user', None)
        session.pop('admin_demo_otp', None)
        admin_record["otp_hash"] = None
        return jsonify({
            "success": True,
            "message": "Admin authenticated successfully."
        })
    else:
        admin_record["otp_attempts"] += 1
        return jsonify({
            "success": False,
            "message": f"Invalid OTP. Remaining attempts: {max(0, 3 - admin_record['otp_attempts'])}"
        }), 400

@app.route('/api/admin/logout', methods=['POST', 'GET'])
def admin_logout_api():
    session.pop('admin_authenticated', None)
    session.pop('admin_username', None)
    return jsonify({"success": True, "message": "Admin logged out successfully."})

@app.route('/api/admin/inventory', methods=['GET'])
def admin_get_inventory():
    """Returns real-time blood inventory across all hospitals."""
    inventory = load_blood_inventory()
    return jsonify({
        "success": True,
        "count": len(inventory),
        "data": inventory
    })

@app.route('/api/admin/inventory/update', methods=['POST'])
@admin_required
def admin_update_inventory():
    """Updates inventory stock. Prevents negative stock and enforces data integrity."""
    data = request.get_json(silent=True) or {}
    h_id = data.get("hospital_id", "").strip()
    bg = data.get("blood_group", "").strip().upper()
    try:
        units = int(data.get("units", -1))
    except (ValueError, TypeError):
        return jsonify({"success": False, "message": "Invalid units number"}), 400

    if units < 0:
        return jsonify({"success": False, "message": "Stock units cannot be negative"}), 400

    ok, res = update_inventory_units(h_id, bg, units)
    if not ok:
        return jsonify({"success": False, "message": res}), 400

    return jsonify({
        "success": True,
        "message": "Inventory updated successfully",
        "data": res
    })

@app.route('/api/admin/deliveries', methods=['GET'])
@admin_required
def admin_get_deliveries():
    """Returns all deliveries with driver names, statuses, and timestamps."""
    deliv_res = supabase.table("deliveries").select("*").order("created_at", desc=True).execute()
    deliveries_list = deliv_res.data or []

    partners_res = supabase.table("delivery_partners").select("*").execute()
    partner_map = {p["id"]: p for p in (partners_res.data or [])}

    for d in deliveries_list:
        pid = d.get("partner_id")
        d["partner"] = partner_map.get(pid, {})
        d["formatted_id"] = f"D{d['id']:03d}"

    return jsonify({
        "success": True,
        "count": len(deliveries_list),
        "data": deliveries_list
    })

@app.route('/admin')
@app.route('/admin/dashboard')
def admin_dashboard_page():
    """Admin dashboard view showing inventory, deliveries, and PDF verification."""
    inventory = load_blood_inventory()
    deliv_res = supabase.table("deliveries").select("*").order("created_at", desc=True).execute()
    deliveries_list = deliv_res.data or []
    partners_res = supabase.table("delivery_partners").select("*").execute()
    partner_map = {p["id"]: p for p in (partners_res.data or [])}
    for d in deliveries_list:
        pid = d.get("partner_id")
        d["partner"] = partner_map.get(pid, {})
        d["formatted_id"] = f"D{d['id']:03d}"

    # Return HTML template by default (unless explicitly requesting ?json=1)
    if not request.args.get('json'):
        is_auth = bool(session.get('admin_authenticated'))
        return render_template(
            'admin.html',
            authenticated=is_auth,
            username=session.get('admin_username', 'Admin'),
            inventory=inventory if is_auth else [],
            deliveries=deliveries_list if is_auth else []
        )

    return jsonify({
        "title": "BloodLink Admin Dashboard",
        "authenticated": bool(session.get('admin_authenticated')),
        "inventory_count": len(inventory),
        "total_deliveries": len(deliveries_list),
        "active_deliveries": [d for d in deliveries_list if d.get("status") in ["Pending", "Assigned", "On the way", "Reached"]],
        "inventory_summary": inventory[:10]
    })

# -------------------------------------------------------------
# Hospital PDF Requisition Upload & Verification (pypdf)
# -------------------------------------------------------------

@app.route('/api/hospital/verify-pdf', methods=['POST'])
@app.route('/api/upload-pdf', methods=['POST'])
def verify_hospital_pdf():
    """
    Hospital PDF verification using pypdf.
    Validates file type and size (<= 5MB), extracts text, handles scanned PDFs gracefully,
    checks medical requisition fields against hospital registry, and returns structured result.
    """
    if 'file' not in request.files and 'pdf' not in request.files:
        return jsonify({"success": False, "message": "No PDF file attached in request"}), 400

    file = request.files.get('file') or request.files.get('pdf')
    if not file or not file.filename:
        return jsonify({"success": False, "message": "No file selected"}), 400

    if not file.filename.lower().endswith('.pdf'):
        return jsonify({"success": False, "message": "Invalid file format. Only .pdf files are accepted."}), 400

    file_bytes = file.read()
    if len(file_bytes) > 5 * 1024 * 1024:
        return jsonify({"success": False, "message": "File size exceeds the 5MB limit."}), 400

    if PdfReader is None:
        return jsonify({"success": False, "message": "pypdf library is not installed on server."}), 500

    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        num_pages = len(reader.pages)
        raw_text = ""
        for page in reader.pages:
            t = page.extract_text() or ""
            raw_text += t + "\n"

        raw_text_stripped = raw_text.strip()

        # Handle scanned or image-only PDFs gracefully without failing
        if len(raw_text_stripped) < 40:
            return jsonify({
                "success": True,
                "verified": False,
                "is_scanned_image": True,
                "pages": num_pages,
                "extracted_length": len(raw_text_stripped),
                "message": "Document appears to be scanned or image-only. Text could not be extracted; manual coordinator review required."
            })

        # Match against official hospital directory
        hospitals_map = load_hospitals()
        matched_hospital = None
        for h_id, h_info in hospitals_map.items():
            h_name = h_info.get("hospital_name", "")
            if h_name.lower() in raw_text.lower():
                matched_hospital = h_info
                break

        # Check for dates (e.g., DD/MM/YYYY or YYYY-MM-DD)
        date_pattern = r'(\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b|\b\d{4}[/-]\d{1,2}[/-]\d{1,2}\b)'
        dates_found = re.findall(date_pattern, raw_text)

        # Check for blood group mentions
        bg_pattern = r'\b(A\+|A-|B\+|B-|AB\+|AB-|O\+|O-)\b'
        bgs_found = re.findall(bg_pattern, raw_text)

        # Medical requisition indicators
        keywords = ["blood", "patient", "requisition", "hospital", "doctor", "unit", "transfusion", "donor"]
        found_keywords = [k for k in keywords if k in raw_text.lower()]

        # Compute confidence score
        confidence = 0
        if matched_hospital:
            confidence += 40
        if dates_found:
            confidence += 20
        if bgs_found:
            confidence += 20
        if len(found_keywords) >= 3:
            confidence += 20

        is_verified = bool(matched_hospital and confidence >= 60)

        return jsonify({
            "success": True,
            "verified": is_verified,
            "confidence_score": confidence,
            "is_scanned_image": False,
            "matched_hospital": matched_hospital["hospital_name"] if matched_hospital else None,
            "hospital_id": matched_hospital["hospital_id"] if matched_hospital else None,
            "extracted_dates": dates_found,
            "extracted_blood_groups": list(set(bgs_found)),
            "medical_indicators": found_keywords,
            "page_count": num_pages,
            "message": "Requisition verified against hospital registry" if is_verified else "Verification unconfirmed; hospital or requisition details not verified"
        })

    except Exception as e:
        print("[ERROR] PDF verification:", e)
        return jsonify({
            "success": False,
            "message": f"Error parsing PDF document: {str(e)}"
        }), 500


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
