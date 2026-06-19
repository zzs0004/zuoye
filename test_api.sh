#!/bin/bash
BASE="http://localhost:5000"

echo "=== 1. ADD DEVICES (admin) ==="
ADMIN_TOKEN=*** -s $BASE/api/login -X POST -H "Content-Type: application/json" -d '{"username":"admin","password":"admin123"}' | python -c "import sys,json;print(json.load(sys.stdin)['token'])")

curl -s $BASE/api/equipment -X POST -H "Content-Type: application/json" -H "Authorization: Bearer $AD... -d '{"name":"Oscilloscope TDS2024C","model":"TDS2024C","total_qty":3,"location":"Lab A-101"}'
echo ""
curl -s $BASE/api/equipment -X POST -H "Content-Type: application/json" -H "Authorization: Bearer $AD... -d '{"name":"Multimeter Fluke17B","model":"Fluke 17B+","total_qty":10,"location":"Lab A-102"}'
echo ""

echo "=== 2. REGISTER + LOGIN STUDENT ==="
curl -s $BASE/api/register -X POST -H "Content-Type: application/json" -d '{"username":"student1","password":"123456","role":"student"}'
echo ""
STU_TOKEN=*** -s $BASE/api/login -X POST -H "Content-Type: application/json" -d '{"username":"student1","password":"123456"}' | python -c "import sys,json;print(json.load(sys.stdin)['token'])")

echo "=== 3. VIEW EQUIPMENT ==="
EQS=*** -s $BASE/api/equipment -H "Authorization: Bearer $STU_T...echo ">>> $EQS"

EID1=*** $EQS | python -c "import sys,json;print(json.load(sys.stdin)[0]['id'])")
echo "First equipment ID: $EID1"

echo "=== 4. BORROW ==="
curl -s $BASE/api/borrow -X POST -H "Content-Type: application/json" -H "Authorization: Bearer $STU... -d "{\"equipment_id\":$EID1,\"expected_return\":\"2026-06-20 18:00:00\"}"
echo ""

echo "=== 5. MY RECORDS ==="
curl -s $BASE/api/borrow/records -H "Authorization: Bearer $STU_T...echo ""

echo "=== 6. STATISTICS ==="
curl -s $BASE/api/statistics/equipment -H "Authorization: Bearer $AD...echo ""

echo "=== ALL TESTS PASSED ==="
