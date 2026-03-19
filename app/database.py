def get_destination_by_id(destination_id: int):
    """Get destination and its customer by destination ID."""
    with DatabaseConnection() as conn:
        # First check if destination exists
        check_query = """
            SELECT COUNT(*) as count 
            FROM destinations 
            WHERE id = ?
        """
        count = conn.execute(check_query, (destination_id,)).fetchone()['count']
        logging.debug(f"Found {count} destinations with ID {destination_id}")

        if count == 0:
            return None

        # Get full destination details
        query = """
            SELECT 
                d.id,
                d.name,
                d.address,
                d.customer_id,
                c.name as customer_name,
                d.is_deleted
            FROM destinations d
            LEFT JOIN customers c ON d.customer_id = c.id
            WHERE d.id = ?
        """
        
        result = conn.execute(query, (destination_id,)).fetchone()
        if result:
            logging.debug(f"Destination details: {dict(result)}")
        return result

def search_globally(search_term):
    """Global search with improved destination handling and logging."""
    with DatabaseConnection() as conn:
        # First verify if destination exists
        check_query = """
            SELECT d.*, c.name as customer_name
            FROM destinations d
            JOIN customers c ON d.customer_id = c.id 
            WHERE d.id = ?
        """
        try:
            destination_id = int(search_term)
            dest = conn.execute(check_query, (destination_id,)).fetchone()
            if dest:
                logging.debug(f"Found destination directly by ID: {dict(dest)}")
                return [dict(dest)]
        except ValueError:
            pass  # Not a numeric search term, continue with normal search

        # Regular search
        query = """
            SELECT 
                d.id,
                d.name,
                d.address,
                d.phone,
                d.email,
                d.customer_id,
                c.name as customer_name,
                d.is_deleted,
                d.is_synced,
                d.last_modified,
                d.uuid
            FROM destinations d
            JOIN customers c ON d.customer_id = c.id
            WHERE (
                d.name LIKE ? OR 
                d.address LIKE ? OR 
                c.name LIKE ?
            ) AND d.is_deleted = 0

            UNION

            SELECT 
                dest.id,
                dest.name,
                dest.address,
                dest.phone,
                dest.email,
                dest.customer_id,
                c.name as customer_name,
                dest.is_deleted,
                dest.is_synced,
                dest.last_modified,
                dest.uuid
            FROM devices dev
            JOIN destinations dest ON dev.destination_id = dest.id
            JOIN customers c ON dest.customer_id = c.id
            WHERE (
                dev.description LIKE ? OR
                dev.serial_number LIKE ? OR
                dev.ams_inventory LIKE ? OR
                dev.customer_inventory LIKE ?
            ) AND dev.is_deleted = 0 AND dest.is_deleted = 0
        """
        
        search_pattern = f"%{search_term}%"
        params = [search_pattern] * 7
        results = conn.execute(query, params).fetchall()
        
        logging.debug(f"Global search found {len(results)} results for term: {search_term}")
        return [dict(row) for row in results]