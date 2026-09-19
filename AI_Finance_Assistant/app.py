from flask import Flask, render_template, request, redirect, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from database import get_connection
from ml_model import predict_category
from forecast import predict_next_month

from datetime import datetime


app = Flask(__name__)
app.secret_key = "finance_assistant_secret_key"


# ---------------- HOME ----------------

@app.route("/")
def index():
    return render_template("index.html")


# ---------------- REGISTER ----------------

@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        name = request.form["name"]
        email = request.form["email"]
        password = request.form["password"]

        hashed_password = generate_password_hash(password)

        connection = get_connection()
        cursor = connection.cursor()

        try:
            cursor.execute(
                """
                INSERT INTO users (name, email, password)
                VALUES (%s, %s, %s)
                """,
                (name, email, hashed_password)
            )

            connection.commit()

            flash("Registration successful. Please login.")

            return redirect("/login")

        except Exception:
            flash("Email already exists.")

        finally:
            cursor.close()
            connection.close()

    return render_template("register.html")


# ---------------- LOGIN ----------------

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        email = request.form["email"]
        password = request.form["password"]

        connection = get_connection()
        cursor = connection.cursor(dictionary=True)

        cursor.execute(
            "SELECT * FROM users WHERE email=%s",
            (email,)
        )

        user = cursor.fetchone()

        cursor.close()
        connection.close()

        if user and check_password_hash(user["password"], password):

            session["user_id"] = user["id"]
            session["user_name"] = user["name"]

            return redirect("/dashboard")

        flash("Invalid email or password.")

    return render_template("login.html")


# ---------------- LOGOUT ----------------

@app.route("/logout")
def logout():

    session.clear()

    return redirect("/")


# ---------------- DASHBOARD ----------------

@app.route("/dashboard")
def dashboard():

    if "user_id" not in session:
        return redirect("/login")

    user_id = session["user_id"]

    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

    now = datetime.now()
    current_month = now.strftime("%Y-%m")

    # Total budget for current month
    cursor.execute(
        """
        SELECT limit_amount
        FROM budgets
        WHERE user_id=%s AND month=%s AND category='Total'
        """,
        (user_id, current_month)
    )

    row = cursor.fetchone()

    if row:
        total_budget = float(row["limit_amount"])
    else:
        # No total budget set -> use sum of category budgets
        cursor.execute(
            """
            SELECT COALESCE(SUM(limit_amount), 0) AS total
            FROM budgets
            WHERE user_id=%s AND month=%s
            """,
            (user_id, current_month)
        )
        total_budget = float(cursor.fetchone()["total"])

    # Total expenses for current month
    cursor.execute(
        """
        SELECT COALESCE(SUM(amount), 0) AS total
        FROM transactions
        WHERE user_id=%s AND type='Expense'
        AND YEAR(date)=%s AND MONTH(date)=%s
        """,
        (user_id, now.year, now.month)
    )

    expenses = float(cursor.fetchone()["total"])

    # Balance = what is left from the budget
    balance = total_budget - expenses

    # Recent transactions
    cursor.execute(
        """
        SELECT *
        FROM transactions
        WHERE user_id=%s
        ORDER BY date DESC, id DESC
        LIMIT 5
        """,
        (user_id,)
    )

    recent_transactions = cursor.fetchall()

    # Category spending
    cursor.execute(
        """
        SELECT category, SUM(amount) AS total
        FROM transactions
        WHERE user_id=%s AND type='Expense'
        GROUP BY category
        """,
        (user_id,)
    )

    category_data = cursor.fetchall()

    cursor.close()
    connection.close()

    categories = [row["category"] for row in category_data]
    category_amounts = [
        float(row["total"]) for row in category_data
    ]

    return render_template(
        "dashboard.html",
        total_budget=total_budget,
        expenses=expenses,
        balance=balance,
        recent_transactions=recent_transactions,
        categories=categories,
        category_amounts=category_amounts
    )


# ---------------- ADD TRANSACTION ----------------

@app.route("/add-transaction", methods=["GET", "POST"])
def add_transaction():

    if "user_id" not in session:
        return redirect("/login")

    if request.method == "POST":

        amount = request.form["amount"]
        date = request.form["date"]
        description = request.form["description"]
        transaction_type = request.form["type"]
        category = request.form.get("category")

        # AI category prediction
        if transaction_type == "Expense":

            predicted_category, confidence = predict_category(
                description
            )

            category = predicted_category

            flash(
                f"AI predicted category: {predicted_category} "
                f"({confidence}% confidence)"
            )

        connection = get_connection()
        cursor = connection.cursor()

        cursor.execute(
            """
            INSERT INTO transactions
            (user_id, date, description, amount, type, category)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                session["user_id"],
                date,
                description,
                amount,
                transaction_type,
                category
            )
        )

        connection.commit()

        cursor.close()
        connection.close()

        return redirect("/transactions")

    return render_template("add_transaction.html")


# ---------------- TRANSACTIONS ----------------

@app.route("/transactions")
def transactions():

    if "user_id" not in session:
        return redirect("/login")

    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

    cursor.execute(
        """
        SELECT *
        FROM transactions
        WHERE user_id=%s
        ORDER BY date DESC
        """,
        (session["user_id"],)
    )

    transactions = cursor.fetchall()

    cursor.close()
    connection.close()

    return render_template(
        "transactions.html",
        transactions=transactions
    )


# ---------------- DELETE TRANSACTION ----------------

@app.route("/delete-transaction/<int:id>")
def delete_transaction(id):

    if "user_id" not in session:
        return redirect("/login")

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        DELETE FROM transactions
        WHERE id=%s AND user_id=%s
        """,
        (id, session["user_id"])
    )

    connection.commit()

    cursor.close()
    connection.close()

    return redirect("/transactions")


# ---------------- BUDGET ----------------

@app.route("/budget", methods=["GET", "POST"])
def budget():

    if "user_id" not in session:
        return redirect("/login")

    user_id = session["user_id"]

    if request.method == "POST":

        month = request.form["month"]
        budget_type = request.form["budget_type"]
        limit_amount = request.form["limit_amount"]

        # Total month budget is stored with category = "Total"
        if budget_type == "total":
            category = "Total"
        else:
            category = request.form["category"]

        connection = get_connection()
        cursor = connection.cursor()

        # Remove old budget for same month + category (avoid duplicates)
        cursor.execute(
            """
            DELETE FROM budgets
            WHERE user_id=%s AND month=%s AND category=%s
            """,
            (user_id, month, category)
        )

        cursor.execute(
            """
            INSERT INTO budgets
            (user_id, month, category, limit_amount)
            VALUES (%s, %s, %s, %s)
            """,
            (user_id, month, category, limit_amount)
        )

        connection.commit()

        cursor.close()
        connection.close()

        flash("Budget saved successfully.")

    connection = get_connection()
    cursor = connection.cursor(dictionary=True)

    cursor.execute(
        """
        SELECT *
        FROM budgets
        WHERE user_id=%s
        ORDER BY month DESC, (category='Total') DESC
        """,
        (user_id,)
    )

    budgets = cursor.fetchall()

    cursor.close()
    connection.close()

    return render_template(
        "budget.html",
        budgets=budgets
    )


# ---------------- PREDICTION ----------------

@app.route("/prediction")
def prediction():

    if "user_id" not in session:
        return redirect("/login")

    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT
            YEAR(date),
            MONTH(date),
            SUM(amount)
        FROM transactions
        WHERE user_id=%s
        AND type='Expense'
        GROUP BY YEAR(date), MONTH(date)
        ORDER BY YEAR(date), MONTH(date)
        """,
        (session["user_id"],)
    )

    rows = cursor.fetchall()

    cursor.close()
    connection.close()

    expenses = [float(row[2]) for row in rows]

    predicted = predict_next_month(expenses)

    return render_template(
        "dashboard.html",
        total_budget=0,
        expenses=0,
        balance=0,
        recent_transactions=[],
        categories=[],
        category_amounts=[],
        prediction=predicted
    )


# ---------------- RUN APPLICATION ----------------

if __name__ == "__main__":
    app.run(debug=True)