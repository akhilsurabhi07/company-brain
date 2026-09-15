"""
Company Brain Technologies Inc.
Payroll & Compensation Processor Microservice
"""

class PayrollProcessor:
    """Calculates monthly employee payroll, tax deductions, and gratuity payouts."""

    @staticmethod
    def calculate_monthly_payroll(basic_salary: float, flexi_wallet: float = 5000.0) -> dict:
        hra = basic_salary * 0.40
        special_allowance = basic_salary * 0.20
        pf_deduction = basic_salary * 0.12
        gross_salary = basic_salary + hra + special_allowance + flexi_wallet
        net_pay = gross_salary - pf_deduction
        return {
            "gross_salary": gross_salary,
            "net_pay": net_pay,
            "pf_deduction": pf_deduction,
            "hra": hra,
        }

    @staticmethod
    def calculate_gratuity(last_drawn_basic: float, years_of_service: float) -> float:
        if years_of_service < 5.0:
            return 0.0
        gratuity = (last_drawn_basic * 15 * years_of_service) / 26
        return min(gratuity, 2000000.0) # Capped at INR 20 Lakhs per Act
