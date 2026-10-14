-- ============================================================================
-- BloodLink: Delivery & Real-Time Tracking Schema (Enhanced)
-- Role: Person 1 (Backend & Database Developer)
-- Compatible with PostgreSQL 12+ / pgAdmin 4 / Supabase / VS Code PostgreSQL
-- ============================================================================

-- 1. Table: delivery_partners
-- Stores rider profile, vehicle information, status, and current GPS coordinates.
CREATE TABLE IF NOT EXISTS delivery_partners (
    id SERIAL PRIMARY KEY,
    partner_name VARCHAR(100) NOT NULL,
    phone VARCHAR(15) NOT NULL UNIQUE,
    vehicle_type VARCHAR(50) NOT NULL,
    location VARCHAR(150) NOT NULL,
    availability_status VARCHAR(20) DEFAULT 'Offline' NOT NULL
        CHECK (availability_status IN ('Available', 'Busy', 'Offline')),
    current_latitude NUMERIC(10, 6),
    current_longitude NUMERIC(10, 6)
);

-- 2. Table: deliveries
-- Stores active and historical blood delivery requests.
-- Supports distinct 'Reached' and 'Delivered' (via recipient OTP) statuses.
CREATE TABLE IF NOT EXISTS deliveries (
    id SERIAL PRIMARY KEY,
    partner_id INT REFERENCES delivery_partners(id) ON DELETE SET NULL,
    customer_name VARCHAR(100) NOT NULL,
    customer_phone VARCHAR(15) NOT NULL,
    blood_group VARCHAR(10) NOT NULL,
    hospital_name VARCHAR(150) NOT NULL,
    destination VARCHAR(255) NOT NULL,
    destination_latitude NUMERIC(10, 6),
    destination_longitude NUMERIC(10, 6),
    status VARCHAR(20) DEFAULT 'Pending' NOT NULL
        CHECK (status IN ('Pending', 'Assigned', 'On the way', 'Reached', 'Delivered', 'Arrived', 'Completed', 'Cancelled')),
    eta_minutes INT DEFAULT 0,
    recipient_otp_hash VARCHAR(255),
    otp_expires_at TIMESTAMP WITH TIME ZONE,
    otp_attempts INT DEFAULT 0,
    delivered_at TIMESTAMP WITH TIME ZONE,
    pickup_hospital_id VARCHAR(20),
    pickup_latitude NUMERIC(10, 6),
    pickup_longitude NUMERIC(10, 6),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 3. Table: location_updates
-- Stores historical GPS breadcrumb tracking points for moving riders over time.
CREATE TABLE IF NOT EXISTS location_updates (
    id SERIAL PRIMARY KEY,
    delivery_id INT NOT NULL REFERENCES deliveries(id) ON DELETE CASCADE,
    partner_id INT NOT NULL REFERENCES delivery_partners(id) ON DELETE CASCADE,
    latitude NUMERIC(10, 6) NOT NULL,
    longitude NUMERIC(10, 6) NOT NULL,
    recorded_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 4. Table: admin_users
-- Stores administrative credentials and 2FA OTP state for admin verification.
CREATE TABLE IF NOT EXISTS admin_users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    current_otp_hash VARCHAR(255),
    otp_expires_at TIMESTAMP WITH TIME ZONE,
    otp_attempts INT DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 5. Table: blood_inventory
-- Centralized inventory table for concurrency control and atomic unit updates.
CREATE TABLE IF NOT EXISTS blood_inventory (
    id SERIAL PRIMARY KEY,
    hospital_id VARCHAR(20) NOT NULL,
    blood_group VARCHAR(10) NOT NULL,
    units INT NOT NULL CHECK (units >= 0),
    status VARCHAR(20) DEFAULT 'Available',
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (hospital_id, blood_group)
);

-- ============================================================================
-- Indexes for Fast Query Performance
-- ============================================================================

-- Faster lookup when assigning free riders
CREATE INDEX IF NOT EXISTS idx_partners_availability 
    ON delivery_partners(availability_status);

-- Faster lookup for active deliveries by partner and status
CREATE INDEX IF NOT EXISTS idx_deliveries_partner_id 
    ON deliveries(partner_id);

CREATE INDEX IF NOT EXISTS idx_deliveries_status 
    ON deliveries(status);

-- Fast lookup for real-time tracking route history and latest rider GPS ping
CREATE INDEX IF NOT EXISTS idx_location_updates_delivery_time 
    ON location_updates(delivery_id, recorded_at DESC);

CREATE INDEX IF NOT EXISTS idx_location_updates_partner_id 
    ON location_updates(partner_id);

CREATE INDEX IF NOT EXISTS idx_inventory_lookup
    ON blood_inventory(hospital_id, blood_group);
