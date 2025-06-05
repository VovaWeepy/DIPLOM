import psycopg2
from psycopg2 import Error

# Database connection parameters
DB_HOST = '5.183.188.132'
DB_PORT = '5432'
DB_NAME = '2025_psql_volod'
DB_USER = '2025_psql_v_usr'
DB_PASSWORD = 'Tllhhldh2loUGKFe'


def get_db_connection():
    try:
        connection = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD
        )
        return connection
    except (Exception, Error) as error:
        print("Error while connecting to PostgreSQL", error)
        return None


def create_users_table():
    connection = get_db_connection()
    if connection:
        try:
            cursor = connection.cursor()

            # Create users table if it doesn't exist
            create_table_query = '''
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username VARCHAR(50) UNIQUE NOT NULL,
                    password VARCHAR(255) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            '''

            cursor.execute(create_table_query)
            connection.commit()
            print("Users table created successfully")

        except (Exception, Error) as error:
            print("Error while creating table:", error)
        finally:
            if connection:
                cursor.close()
                connection.close()
                print("PostgreSQL connection is closed")


# Create the users table when the module is imported
if __name__ == "__main__":
    create_users_table()


# Example of how to use the connection in your application
def add_user(username, password):
    connection = get_db_connection()
    if connection:
        try:
            cursor = connection.cursor()
            insert_query = "INSERT INTO users (username, password) VALUES (%s, %s)"
            cursor.execute(insert_query, (username, password))
            connection.commit()
            print("User added successfully")
        except (Exception, Error) as error:
            print("Error while adding user:", error)
        finally:
            if connection:
                cursor.close()
                connection.close()
