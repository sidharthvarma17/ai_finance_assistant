import mysql.connector


def get_connection():
    connection = mysql.connector.connect(
        host="localhost",
        user="root",
        password="S@iChetana@123",
        database="ai_finance_assistant"
    )

    return connection