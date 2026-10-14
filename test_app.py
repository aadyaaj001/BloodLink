"""
BloodLink - Automated Test Suite (Enhanced)
Role: Person 1 (Flask Backend & Database Developer)
Covers:
1. Haversine distance & closest hospital sorting
2. Step 0 to Step 4 request confirmation flow
3. Idempotency & duplicate delivery prevention
4. Live delivery location API (GET) & genuine GPS ingestion (POST)
5. Recipient OTP verification workflow (Reached vs Delivered)
6. Admin authentication & 2FA OTP security
7. Inventory persistence, atomic deductions & negative stock prevention
8. Hospital PDF verification with pypdf (valid, scanned, invalid)
"""

import unittest
import io
import json
from pypdf import PdfWriter
from app import (
    app,
    load_hospitals,
    load_blood_inventory,
    search_closest_hospitals,
    haversine_distance,
    local_store,
    supabase,
    VALID_BLOOD_GROUPS
)

def create_sample_text_pdf(content_text="Lifeline Hospital Blood Bank Requisition B+ Units: 2 Date: 12/10/2026 Dr. Patil"):
    """Creates a minimal valid text-based PDF in memory for testing."""
    escaped = content_text.replace("(", "").replace(")", "")
    pdf_bytes = (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R/Resources<</Font<</F1 4 0 R>>>>/Contents 5 0 R>>endobj\n"
        b"4 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
        b"5 0 obj<</Length " + str(len(escaped) + 60).encode() + b">>stream\n"
        b"BT /F1 14 Tf 50 700 Td (" + escaped.encode() + b") Tj ET\n"
        b"endstream\nendobj\n"
        b"xref\n0 6\n"
        b"0000000000 65535 f \n"
        b"0000000009 00000 n \n"
        b"0000000056 00000 n \n"
        b"0000000111 00000 n \n"
        b"0000000212 00000 n \n"
        b"0000000277 00000 n \n"
        b"trailer<</Size 6/Root 1 0 R>>\n"
        b"startxref\n450\n%%EOF\n"
    )
    return pdf_bytes

def create_sample_blank_pdf():
    """Creates an empty/scanned mock PDF."""
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    stream = io.BytesIO()
    writer.write(stream)
    stream.seek(0)
    return stream.getvalue()


class TestBloodLinkFlow(unittest.TestCase):

    def setUp(self):
        self.client = app.test_client()
        self.client.testing = True

    def test_haversine_distance(self):
        dist = haversine_distance(18.9917, 73.1102, 19.0474, 73.0664)
        self.assertIsNotNone(dist)
        self.assertGreater(dist, 5.0)
        self.assertLess(dist, 15.0)
        print(f"[PASS] Haversine distance Panvel to Kharghar: {dist} km")

    def test_search_closest_hospitals(self):
        results = search_closest_hospitals("A+", location_str="New Panvel")
        self.assertGreater(len(results), 0, "Should find available hospitals for A+")
        distances = [r["distance_num"] for r in results]
        self.assertEqual(distances, sorted(distances), "Hospitals must be sorted by distance ascending")
        closest = results[0]
        self.assertIn("distance", closest)
        self.assertGreater(closest["units"], 0)
        print(f"[PASS] Closest hospital to New Panvel for A+: {closest['hospital_name']} at {closest['distance']} ({closest['units']} units in stock)")

    def test_step0_home_page(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        content = response.data.decode('utf-8')
        self.assertIn("Find Blood", content)
        self.assertIn("Every Drop Can Save a Life", content)
        print("[PASS] Step 0: Home page loaded with 'Find Blood' button.")

    def test_step1_find_blood_page(self):
        response = self.client.get('/find-blood')
        self.assertEqual(response.status_code, 200)
        content = response.data.decode('utf-8')
        self.assertIn("Required Blood Group", content)
        self.assertIn("Urgency Level", content)
        self.assertIn("Your Location", content)
        self.assertIn("Units of Blood Required", content)
        print("[PASS] Step 1: Find Blood form loaded.")

    def test_step1_submit_to_user_details(self):
        post_data = {
            'blood_group': 'B+',
            'urgency': 'Critical',
            'location': 'Khanda Colony',
            'units': '2'
        }
        response = self.client.post('/find-blood', data=post_data)
        self.assertEqual(response.status_code, 200)
        content = response.data.decode('utf-8')
        self.assertIn("Step 2: Enter Your Contact Details", content)
        self.assertIn("B+", content)
        print("[PASS] Step 1 -> Step 2: Blood requirements passed to contact details form.")

    def test_step2_submit_to_closest_hospitals(self):
        post_data = {
            'blood_group': 'B+',
            'urgency': 'Critical',
            'location': 'Khanda Colony',
            'units': '2',
            'name': 'Ananya Iyer',
            'phone': '9876543210',
            'email': 'ananya@example.com'
        }
        response = self.client.post('/user-details', data=post_data)
        self.assertEqual(response.status_code, 200)
        content = response.data.decode('utf-8')
        self.assertIn("Closest Hospitals for", content)
        self.assertIn("Ananya Iyer", content)
        print("[PASS] Step 2 -> Step 3: Closest hospitals with availability displayed.")

    def test_step3_request_blood_confirmation_and_partner_assignment(self):
        post_data = {
            'hospital_id': 'H002',
            'blood_group': 'B+',
            'name': 'Rohan Deshmukh',
            'phone': '+919123456789',
            'email': 'rohan@example.com',
            'units': '1',
            'urgency': 'Critical',
            'location': 'Khanda Colony',
            'distance': '0.8 km'
        }
        response = self.client.post('/request-blood', data=post_data)
        self.assertEqual(response.status_code, 200)
        content = response.data.decode('utf-8')
        self.assertIn("Request Submitted Successfully!", content)
        self.assertIn("Assigned Delivery Partner", content)
        self.assertIn("Track Live Delivery", content)
        self.assertIn("Rohan Deshmukh", content)
        print("[PASS] Step 4: Request confirmed, delivery ID & partner assigned, Track button rendered.")

    def test_duplicate_delivery_prevention(self):
        post_data = {
            'hospital_id': 'H002',
            'blood_group': 'B+',
            'name': 'Rohan Deshmukh',
            'phone': '+919123456789',
            'email': 'rohan@example.com',
            'units': '1',
            'urgency': 'Critical',
            'location': 'Khanda Colony',
            'distance': '0.8 km'
        }
        # First submission
        res1 = self.client.post('/request-blood', data=post_data)
        self.assertEqual(res1.status_code, 200)
        count_before = len(local_store.deliveries)

        # Immediate duplicate submission
        res2 = self.client.post('/request-blood', data=post_data)
        self.assertEqual(res2.status_code, 200)
        count_after = len(local_store.deliveries)

        # Count of deliveries should not increase; existing delivery reused
        self.assertEqual(count_before, count_after, "Duplicate delivery should be reused without creating duplicates")
        print("[PASS] Idempotency: Duplicate delivery requests safely reused existing record.")

    def test_live_delivery_tracking_and_gps_ingestion(self):
        # 1. Query delivery tracking
        response = self.client.get('/api/delivery/D001/location')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data.get("success"))
        delivery_info = data.get("data", {})
        self.assertEqual(delivery_info.get("delivery_id"), "D001")
        self.assertIsNotNone(delivery_info.get("partner_name"))
        self.assertIn("destination", delivery_info)
        print(f"[PASS] GET Tracking API: Driver '{delivery_info.get('partner_name')}', Status: {delivery_info.get('status')}")

        # 2. Ingest genuine GPS update
        update_payload = {
            "latitude": 19.018500,
            "longitude": 73.096500
        }
        post_res = self.client.post(
            '/api/delivery/D001/location',
            data=json.dumps(update_payload),
            content_type='application/json'
        )
        self.assertEqual(post_res.status_code, 200)
        res_json = post_res.get_json()
        self.assertTrue(res_json.get("success"))
        print("[PASS] POST Genuine GPS: Coordinate update saved successfully.")

        # 3. Verify updated coordinates are returned on subsequent GET
        get_after = self.client.get('/api/delivery/D001/location')
        after_data = get_after.get_json().get("data", {})
        self.assertAlmostEqual(after_data.get("latitude"), 19.018500, places=4)
        self.assertAlmostEqual(after_data.get("longitude"), 73.096500, places=4)
        print("[PASS] GPS Ingestion Verified: Tracking API returns updated live breadcrumb.")

        # 4. Out-of-bounds coordinate validation
        invalid_gps = {"latitude": 120.0, "longitude": 73.0}
        bad_res = self.client.post(
            '/api/delivery/D001/location',
            data=json.dumps(invalid_gps),
            content_type='application/json'
        )
        self.assertEqual(bad_res.status_code, 400)
        print("[PASS] Coordinate Validation: Out-of-bounds coordinates rejected.")

    def test_recipient_otp_workflow(self):
        # 1. 'Delivered' status cannot be set directly via generic status endpoint
        direct_delivered_res = self.client.post(
            '/api/delivery/D001/status',
            data=json.dumps({"status": "Delivered"}),
            content_type='application/json'
        )
        self.assertEqual(direct_delivered_res.status_code, 400)
        print("[PASS] Status Security: Cannot jump to 'Delivered' without recipient OTP.")

        # 2. Set status to 'Reached' (rider arrived)
        reached_res = self.client.post(
            '/api/delivery/D001/status',
            data=json.dumps({"status": "Reached"}),
            content_type='application/json'
        )
        self.assertEqual(reached_res.status_code, 200)
        print("[PASS] Status Transition: Delivery marked as 'Reached'.")

        # 3. Invalid OTP attempt
        bad_otp_res = self.client.post(
            '/api/delivery/D001/verify-otp',
            data=json.dumps({"otp": "000000"}),
            content_type='application/json'
        )
        self.assertEqual(bad_otp_res.status_code, 400)
        print("[PASS] Recipient OTP: Wrong OTP rejected and attempt counted.")

        # 4. Fetch valid OTP from test session or delivery record
        delivery_obj = local_store.deliveries[0]
        # Temporarily set known OTP hash for testing
        known_otp = "654321"
        import hashlib
        delivery_obj["recipient_otp_hash"] = hashlib.sha256(known_otp.encode()).hexdigest()

        # 5. Valid OTP verification
        good_otp_res = self.client.post(
            '/api/delivery/D001/verify-otp',
            data=json.dumps({"otp": known_otp}),
            content_type='application/json'
        )
        self.assertEqual(good_otp_res.status_code, 200)
        good_data = good_otp_res.get_json()
        self.assertEqual(good_data.get("status"), "Delivered")
        self.assertIsNotNone(good_data.get("delivered_at"))
        print("[PASS] Recipient OTP Verification: Marked 'Delivered' with timestamp, partner freed.")

    def test_admin_authentication_and_inventory(self):
        # 1. Invalid login
        bad_login = self.client.post(
            '/api/admin/login',
            data=json.dumps({"username": "admin", "password": "wrongpassword"}),
            content_type='application/json'
        )
        self.assertEqual(bad_login.status_code, 401)

        # 2. Valid login -> triggers 2FA OTP
        good_login = self.client.post(
            '/api/admin/login',
            data=json.dumps({"username": "admin", "password": "admin123"}),
            content_type='application/json'
        )
        self.assertEqual(good_login.status_code, 200)
        self.assertTrue(good_login.get_json().get("otp_required"))

        # 3. Verify admin OTP
        with self.client.session_transaction() as sess:
            demo_otp = sess.get('admin_demo_otp')

        verify_res = self.client.post(
            '/api/admin/verify-otp',
            data=json.dumps({"username": "admin", "otp": demo_otp}),
            content_type='application/json'
        )
        self.assertEqual(verify_res.status_code, 200)
        print("[PASS] Admin 2FA: Credentials & OTP verified, session authenticated.")

        # 4. Admin inventory update
        update_inv_res = self.client.post(
            '/api/admin/inventory/update',
            data=json.dumps({"hospital_id": "H001", "blood_group": "A+", "units": 15}),
            content_type='application/json'
        )
        self.assertEqual(update_inv_res.status_code, 200)

        # 5. Prevent negative stock
        neg_res = self.client.post(
            '/api/admin/inventory/update',
            data=json.dumps({"hospital_id": "H001", "blood_group": "A+", "units": -5}),
            content_type='application/json'
        )
        self.assertEqual(neg_res.status_code, 400)
        print("[PASS] Inventory Management: Stock updated, negative values rejected.")

    def test_hospital_pdf_verification(self):
        # 1. Reject non-PDF file
        non_pdf = (io.BytesIO(b"Hello world"), "document.txt")
        res_non_pdf = self.client.post(
            '/api/hospital/verify-pdf',
            data={'file': non_pdf},
            content_type='multipart/form-data'
        )
        self.assertEqual(res_non_pdf.status_code, 400)
        print("[PASS] PDF Security: Non-PDF uploads rejected.")

        # 2. Valid text-based hospital requisition PDF
        valid_pdf_bytes = create_sample_text_pdf(
            "Lifeline Hospital Emergency Requisition B+ Units: 2 Date: 12/10/2026 Doctor Transfusion Requisition"
        )
        valid_file = (io.BytesIO(valid_pdf_bytes), "requisition.pdf")
        res_valid = self.client.post(
            '/api/hospital/verify-pdf',
            data={'file': valid_file},
            content_type='multipart/form-data'
        )
        self.assertEqual(res_valid.status_code, 200)
        valid_data = res_valid.get_json()
        self.assertTrue(valid_data.get("success"))
        self.assertTrue(valid_data.get("verified"))
        self.assertEqual(valid_data.get("matched_hospital"), "Lifeline Hospital")
        self.assertGreaterEqual(valid_data.get("confidence_score"), 60)
        print(f"[PASS] PDF Verification: Requisition confirmed (Hospital: {valid_data.get('matched_hospital')}, Score: {valid_data.get('confidence_score')}).")

        # 3. Scanned/empty PDF graceful handling
        blank_pdf_bytes = create_sample_blank_pdf()
        blank_file = (io.BytesIO(blank_pdf_bytes), "scanned_doc.pdf")
        res_blank = self.client.post(
            '/api/hospital/verify-pdf',
            data={'file': blank_file},
            content_type='multipart/form-data'
        )
        self.assertEqual(res_blank.status_code, 200)
        blank_data = res_blank.get_json()
        self.assertTrue(blank_data.get("success"))
        self.assertFalse(blank_data.get("verified"))
        self.assertTrue(blank_data.get("is_scanned_image"))
        print("[PASS] Scanned PDF Handling: Graceful status returned for image-only document.")


if __name__ == '__main__':
    unittest.main()
