# backend/department_mapper.py

def get_department(category):
    department_map = {
        "Road & Infrastructure Issues": "Public Works Department",
        "Water Supply Issues": "Water Supply Department",
        "Electricity Issues": "Electricity Board",
        "Garbage & Sanitation Issues": "Municipal Sanitation Department",
        "Public Safety & Law Issues": "Police Department",
        "Health & Medical Issues": "Health Department",
        "Transportation Issues": "Transport Department",
        "Pollution & Environment Issues": "Environment Control Board",
        "Government Service Delivery Issues": "Government Administration",
        "Civic Facility Issues": "Municipal Corporation",
        "Digital / IT Services Issues": "IT Services Department",
        "Disaster & Emergency Issues": "Disaster Management Authority",
        "Education & School Issues": "Education Department",
        "Animal & Wildlife Issues": "Animal Welfare Department"
    }

    return department_map.get(category, "General Administration")
