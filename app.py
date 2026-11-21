import os, base64, json, sqlite3, uuid
from flask import Flask, render_template, request, jsonify
from google import genai
from google.genai import types
from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

class Config:
    GEMINI_KEYS = [
        os.getenv("GEMINI_API_KEY_1", ""),
        os.getenv("GEMINI_API_KEY_2", ""),
        os.getenv("GEMINI_API_KEY_3", ""),
    ]
    MODELS = [
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite-preview-06-17",
        "gemini-2.0-flash",
        "gemini-2.5-pro",
    ]

Config.GEMINI_KEYS = [k.strip() for k in Config.GEMINI_KEYS if k and k.strip()]

DB_PATH = 'industrial_iq.db'

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            machine_type TEXT NOT NULL,
            health_score INTEGER NOT NULL,
            risk_level TEXT NOT NULL,
            sensor_data TEXT NOT NULL,
            image_path TEXT,
            vision_data TEXT,
            recommendations TEXT NOT NULL
        )
    ''')
    conn.commit()
    conn.close()

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

MACHINE_SENSORS = {
    "CNC Machine": {
        "description": "Computer Numerical Control precision machining center",
        "icon": "⚙️",
        "sensors": {
            "temperature":  {"label":"Spindle Temp",    "unit":"°C",    "placeholder":"70",   "safe":(0,70),     "warn":(70,95),    "crit":(95,5000),    "icon":"temp"},
            "vibration":    {"label":"Vibration",       "unit":"mm/s",  "placeholder":"3.5",  "safe":(0,3.5),    "warn":(3.5,7.1),  "crit":(7.1,1000),   "icon":"vib"},
            "current":      {"label":"Spindle Current", "unit":"A",     "placeholder":"20",   "safe":(0,20),     "warn":(20,32),    "crit":(32,5000),    "icon":"current"},
            "spindle_rpm":  {"label":"Spindle RPM",     "unit":"RPM",   "placeholder":"3500", "safe":(2000,6000),"warn":(6000,8000),"crit":(8000,20000) and (0,1999),"icon":"rpm"},
            "coolant_flow": {"label":"Coolant Flow",    "unit":"L/min", "placeholder":"8",    "safe":(5,15),     "warn":(3,5),      "crit":(0,3),       "icon":"flow"},
        }
    },
    "Conveyor Belt": {
        "description": "Industrial material transport conveyor system",
        "icon": "🔄",
        "sensors": {
            "temperature":  {"label":"Motor Temp",      "unit":"°C",    "placeholder":"55",   "safe":(0,65),     "warn":(65,90),    "crit":(90,500),    "icon":"temp"},
            "vibration":    {"label":"Vibration",       "unit":"mm/s",  "placeholder":"2.0",  "safe":(0,4.0),    "warn":(4.0,9.0),  "crit":(9.0,100),   "icon":"vib"},
            "current":      {"label":"Motor Current",   "unit":"A",     "placeholder":"22",   "safe":(0,25),     "warn":(25,38),    "crit":(38,500),    "icon":"current"},
            "belt_speedrpm":{"label":"Belt Speed RPM",  "unit":"RPM",   "placeholder":"1200",  "safe":(800,1200), "warn":(600,800),  "crit":(0,600) and (1200,2000),"icon":"rpm"},
            "load_weight":  {"label":"Load Weight",     "unit":"kg",    "placeholder":"850",  "safe":(0,1000),   "warn":(1000,1400),"crit":(1400,9999), "icon":"weight"},
        }
    },
    "Air Compressor": {
        "description": "Industrial reciprocating / screw air compressor",
        "icon": "💨",
        "sensors": {
            "temperature":  {"label":"Discharge Temp",  "unit":"°C",    "placeholder":"95",   "safe":(0,100),    "warn":(100,130),  "crit":(130,500),   "icon":"temp"},
            "vibration":    {"label":"Vibration",       "unit":"mm/s",  "placeholder":"5.0",  "safe":(0,5.0),    "warn":(5.0,11.0), "crit":(11.0,100),  "icon":"vib"},
            "pressure":     {"label":"Outlet Pressure", "unit":"bar",   "placeholder":"10",  "safe":(6,10),     "warn":(10,13),    "crit": (0,4) and (13,1000),     "icon":"pressure"},
            "current":      {"label":"Motor Current",   "unit":"A",     "placeholder":"38",   "safe":(0,45),     "warn":(45,60),    "crit":(60,500),    "icon":"current"},
            "rpm":          {"label":"Motor RPM",       "unit":"RPM",   "placeholder":"1450", "safe":(1400,1500),"warn":(1200,1400),"crit":(0,1200) and (1500,3000),"icon":"rpm"},
            "oil_pressure": {"label":"Oil Pressure",    "unit":"bar",   "placeholder":"3.5",  "safe":(2.5,5),    "warn":(1.5,2.5),  "crit":(0,1.5),     "icon":"pressure"},
        }
    },
    "Hydraulic Press": {
        "description": "High-force hydraulic forming and stamping press",
        "icon": "🔩",
        "sensors": {
            "temperature":  {"label":"Oil Temp",        "unit":"°C",    "placeholder":"48",   "safe":(30,60),    "warn":(60,80),    "crit":(80,500),    "icon":"temp"},
            "pressure":     {"label":"System Pressure", "unit":"bar",   "placeholder":"180",  "safe":(150,200),  "warn":(200,250),  "crit":(250,500),   "icon":"pressure"},
            "vibration":    {"label":"Vibration",       "unit":"mm/s",  "placeholder":"2.5",  "safe":(0,4.0),    "warn":(4.0,8.0),  "crit":(8.0,100),   "icon":"vib"},
            "current":      {"label":"Pump Current",    "unit":"A",     "placeholder":"55",   "safe":(0,60),     "warn":(60,80),    "crit":(80,500),    "icon":"current"},
            "cycle_rate":   {"label":"Cycle Rate",      "unit":"cyc/m", "placeholder":"12",   "safe":(8,20),     "warn":(20,30),    "crit":(30,200),    "icon":"rpm"},
            "oil_level":    {"label":"Oil Level",       "unit":"%",     "placeholder":"85",   "safe":(60,100),   "warn":(40,60),    "crit":(0,40),      "icon":"flow"},
        }
    },

    
    "Industrial Pump": {
        "description": "Centrifugal / positive displacement industrial pump",
        "icon": "🌀",
        "sensors": {
            "temperature":  {"label":"Bearing Temp",    "unit":"°C",    "placeholder":"55",   "safe":(0,70),     "warn":(70,90),    "crit":(90,500),    "icon":"temp"},
            "vibration":    {"label":"Vibration",       "unit":"mm/s",  "placeholder":"2.8",  "safe":(0,4.5),    "warn":(4.5,11.2), "crit":(11.2,100),  "icon":"vib"},
            "pressure":     {"label":"Discharge Press", "unit":"bar",   "placeholder":"6.0",  "safe":(4,9),      "warn":(9,12),     "crit":(12,100),    "icon":"pressure"},
            "flow_rate":    {"label":"Flow Rate",       "unit":"m³/h",  "placeholder":"45",   "safe":(30,80),    "warn":(20,30),    "crit":(0,20),      "icon":"flow"},
            "rpm":          {"label":"Impeller RPM",    "unit":"RPM",   "placeholder":"1450", "safe":(1200,1800),"warn":(900,1200), "crit":(0,900),     "icon":"rpm"},
            "current":      {"label":"Motor Current",   "unit":"A",     "placeholder":"28",   "safe":(0,32),     "warn":(32,45),    "crit":(45,500),    "icon":"current"},
        }
    },
    "Lathe Machine": {
        "description": "Industrial engine lathe / CNC turning center",
        "icon": "🔧",
        "sensors": {
            "spindle_rpm":  {"label":"Spindle RPM",     "unit":"RPM",   "placeholder":"1200", "safe":(500,3000), "warn":(3000,4500),"crit":(4500,10000),"icon":"rpm"},
            "temperature":  {"label":"Bearing Temp",    "unit":"°C",    "placeholder":"58",   "safe":(0,70),     "warn":(70,95),    "crit":(95,500),    "icon":"temp"},
            "vibration":    {"label":"Vibration",       "unit":"mm/s",  "placeholder":"1.8",  "safe":(0,3.5),    "warn":(3.5,7.1),  "crit":(7.1,100),   "icon":"vib"},
            "current":      {"label":"Spindle Current", "unit":"A",     "placeholder":"22",   "safe":(0,25),     "warn":(25,38),    "crit":(38,500),    "icon":"current"},
            "feed_rate":    {"label":"Feed Rate",       "unit":"mm/min","placeholder":"150",  "safe":(50,400),   "warn":(400,600),  "crit":(600,9999),  "icon":"speed"},
        }
    },
   
}

def allowed_file(fn):
    return '.' in fn and fn.rsplit('.',1)[1].lower() in ALLOWED_EXTENSIONS

def get_cfg(mt):
    return MACHINE_SENSORS.get(mt, MACHINE_SENSORS["CNC Machine"])

def analyze_sensors(sensor_data, machine_type):
    defs = get_cfg(machine_type)["sensors"]
    score, issues, statuses = 100, [], {}
    for param, value in sensor_data.items():
        if value is None or value == '': statuses[param]='N/A'; continue
        value = float(value)
        t = defs.get(param)
        if not t: continue
        clo,chi = t['crit']; wlo,whi = t['warn']
        label,unit = t['label'],t['unit']
        low_bad = (clo==0 and chi<wlo)
        if low_bad:
            if clo<=value<=chi: status='CRITICAL';score-=25;issues.append({'parameter':param,'label':label,'value':value,'unit':unit,'level':'critical','message':f"{label} at {value}{unit} — critically low"})
            elif wlo<=value<=whi: status='WARNING';score-=10;issues.append({'parameter':param,'label':label,'value':value,'unit':unit,'level':'warning','message':f"{label} at {value}{unit} — below safe minimum"})
            else: status='NORMAL'
        else:
            if clo<=value<=chi: status='CRITICAL';score-=25;issues.append({'parameter':param,'label':label,'value':value,'unit':unit,'level':'critical','message':f"{label} at {value}{unit} — exceeds critical limit"})
            elif wlo<=value<=whi: status='WARNING';score-=10;issues.append({'parameter':param,'label':label,'value':value,'unit':unit,'level':'warning','message':f"{label} at {value}{unit} — exceeds warning threshold"})
            else: status='NORMAL'
        statuses[param]=status
    score=max(0,min(100,score))
    risk='LOW RISK' if score>=80 else 'MODERATE RISK' if score>=60 else 'HIGH RISK' if score>=40 else 'CRITICAL RISK'
    return {'score':score,'risk_level':risk,'issues':issues,'statuses':statuses,
            'crit_count':sum(1 for i in issues if i['level']=='critical'),
            'warn_count':sum(1 for i in issues if i['level']=='warning')}

def generate_recommendations(sa, machine_type):
    issues,score,recs=sa['issues'],sa['score'],[]
    ip={i['parameter']:i['level'] for i in issues}
    if ip.get('temperature')=='critical': recs.append({'priority':'IMMEDIATE','action':'Emergency Thermal Shutdown','detail':'Temperature critically exceeded. Shutdown immediately. Inspect cooling system, lubricant levels, and ventilation before restart.'})
    elif ip.get('temperature')=='warning': recs.append({'priority':'URGENT','action':'Cooling System Inspection','detail':'Temperature above safe limit. Verify coolant flow, clean heat exchangers, check fan operation and thermal insulation.'})
    if ip.get('vibration')=='critical': recs.append({'priority':'IMMEDIATE','action':'Halt — Vibration Critical','detail':'Critical vibration detected. Stop machine immediately. Inspect bearings, shaft alignment, and all mounting fasteners.'})
    elif ip.get('vibration')=='warning': recs.append({'priority':'URGENT','action':'Vibration & Bearing Analysis','detail':'Schedule dynamic balancing and bearing inspection within 72 hours. Check coupling alignment and foundation.'})
    for k in ('pressure','oil_pressure'):
        if ip.get(k) in ('critical','warning'): recs.append({'priority':'URGENT','action':'Pressure System Inspection','detail':'Abnormal pressure detected. Inspect relief valves, seals, filters, and fluid levels immediately.'}); break
    if ip.get('current') in ('critical','warning'): recs.append({'priority':'URGENT','action':'Electrical Load Inspection','detail':'Abnormal current detected. Inspect motor windings, drive settings, contactor condition, and power supply balance.'})
    for k in ('rpm','spindle_rpm','belt_speed','cycle_time'):
        if ip.get(k) in ('critical','warning'): recs.append({'priority':'SOON','action':'Speed & Drive System Check','detail':'Speed parameter outside operating range. Check VFD/servo settings, drive belt tension, and tachometer calibration.'}); break
    for k in ('coolant_flow','flow_rate','oil_level'):
        if ip.get(k) in ('critical','warning'): recs.append({'priority':'URGENT','action':'Fluid / Flow Inspection','detail':'Flow or level out of range. Check pump operation, filter blockage, and inspect for leaks in the fluid circuit.'}); break
    for k in ('load_weight','joint_torque','cutting_force'):
        if ip.get(k) in ('critical','warning'): recs.append({'priority':'SOON','action':'Mechanical Load Review','detail':'Excessive mechanical load. Review operating parameters, reduce throughput, and inspect drive components.'}); break
    if ip.get('position_err') in ('critical','warning'): recs.append({'priority':'URGENT','action':'Calibration & Positioning Check','detail':'Position error exceeds tolerance. Re-calibrate robot, check encoder feedback, and inspect joint wear.'})
    if score>=85: recs.append({'priority':'ROUTINE','action':'Standard Preventive Maintenance','detail':'Machine operating normally. Follow scheduled PM intervals per OEM guidelines and log this baseline reading.'})
    elif score>=60 and not recs: recs.append({'priority':'PLANNED','action':'Schedule Service Within 2 Weeks','detail':'Minor degradation detected. Plan preventive service: lubrication, alignment check, component inspection.'})
    if not recs: recs.append({'priority':'ROUTINE','action':'Continue Standard Monitoring','detail':'No immediate action required. Maintain inspection schedule, review trends weekly, and log all readings.'})
    return recs

def build_vision_prompt(machine_type):
    return f"""You are an expert industrial machine vision AI analyzing a photograph of a {machine_type}.

Examine the image carefully and return a JSON object with EXACTLY this structure (no markdown, no explanation, just raw JSON):

{{
  "machine_identified": "What machine you see in the image (be specific about make/model if visible)",
  "machine_condition": "GOOD | FAIR | POOR | CRITICAL",
  "overall_visual_summary": "2-3 sentence plain-English summary of what you see and the overall condition",
  "defects_found": [
    {{
      "defect_type": "Name of defect (e.g. Belt Cracking, Oil Leak, Corrosion, Misalignment, Burn Marks)",
      "location": "Where exactly on the machine",
      "severity": "LOW | MEDIUM | HIGH | CRITICAL",
      "description": "What you see — specific details about this defect"
    }}
  ],
  "cleanliness": "Clean | Dirty | Heavily Soiled | Oil-contaminated",
  "visible_wear_level": "None | Minor | Moderate | Heavy | Severe",
  "immediate_safety_concern": true,
  "manager_actions": [
    "Specific action the factory manager should take immediately or soon (plain English, no jargon)"
  ],
  "estimated_remaining_life": "Rough estimate e.g. 2-4 weeks before critical failure if no action taken"
}}

If no defects are found, return an empty array for defects_found.
If the image is not of a machine or is unclear, set machine_identified to "Unknown / Image unclear".
Return ONLY the JSON. No backticks. No explanation."""

def call_gemini(prompt_text, image_b64=None, image_mime=None):
    if not Config.GEMINI_KEYS:
        raise RuntimeError("No Gemini API keys configured. Add GEMINI_API_KEY_1 to .env")
    last_err = None
    for api_key in Config.GEMINI_KEYS:
        for model in Config.MODELS:
            try:
                client = genai.Client(api_key=api_key)
                parts = []
                if image_b64 and image_mime:
                    parts.append(types.Part.from_bytes(data=base64.b64decode(image_b64), mime_type=image_mime))
                parts.append(types.Part.from_text(text=prompt_text))
                response = client.models.generate_content(
                    model=model,
                    contents=[types.Content(role="user", parts=parts)],
                    config=types.GenerateContentConfig(temperature=0.3, max_output_tokens=1500)
                )
                text = response.text.strip()
                print(f"✅ Gemini OK: {model} (key ...{api_key[-6:]})")
                return text, model
            except Exception as e:
                err = str(e).lower()
                last_err = str(e)
                if any(x in err for x in ["quota","429","rate","limit","exhausted","resource_exhausted"]):
                    print(f"⚠️  Rate limit {model} → next")
                else:
                    print(f"⚠️  Error {model}: {str(e)[:80]} → next")
    raise RuntimeError(f"All Gemini keys/models exhausted. Last error: {last_err}")

@app.route('/')
def index():
    return render_template('index.html', machines=list(MACHINE_SENSORS.keys()))

@app.route('/sensors')
def sensors_page():
    return render_template('sensors.html')

@app.route('/api/machines')
def list_machines():
    return jsonify([{'id':k,'description':v['description'],'sensor_count':len(v['sensors']),'icon':v['icon']}
                    for k,v in MACHINE_SENSORS.items()])

@app.route('/api/machine-sensors/<path:machine_type>')
def machine_sensors_api(machine_type):
    cfg = MACHINE_SENSORS.get(machine_type)
    if not cfg: return jsonify({'error':'Unknown machine type'}), 404
    return jsonify({
        'machine_type':machine_type,'description':cfg['description'],'icon':cfg['icon'],
        'sensors':{k:{'label':s['label'],'unit':s['unit'],'placeholder':s['placeholder'],
                       'icon':s['icon'],'safe':list(s['safe']),'warn':list(s['warn']),'crit':list(s['crit'])}
                   for k,s in cfg['sensors'].items()}
    })

@app.route('/api/analyze', methods=['POST'])
def analyze():
    try:
        machine_type = request.form.get('machine_type','CNC Machine')
        cfg = get_cfg(machine_type)
        sensor_keys = list(cfg['sensors'].keys())
        sensor_data = {k: request.form.get(k) or None for k in sensor_keys}
        if not any(v for v in sensor_data.values()):
            return jsonify({'error':'Please provide at least one sensor reading.'}), 400

        sa   = analyze_sensors(sensor_data, machine_type)
        recs = generate_recommendations(sa, machine_type)

        image_b64=None; image_mime='image/jpeg'; has_image=False; image_path=None
        if 'image' in request.files:
            f = request.files['image']
            if f and f.filename and allowed_file(f.filename):
                raw = f.read()
                image_b64  = base64.standard_b64encode(raw).decode()
                ext        = f.filename.rsplit('.',1)[1].lower()
                image_mime = {'jpg':'image/jpeg','jpeg':'image/jpeg','png':'image/png',
                              'gif':'image/gif','webp':'image/webp'}.get(ext,'image/jpeg')
                has_image  = True
                
                # Save the image to static/uploads
                os.makedirs(os.path.join('static', 'uploads'), exist_ok=True)
                img_filename = f"{uuid.uuid4().hex}.{ext}"
                image_path = f"uploads/{img_filename}"
                with open(os.path.join('static', 'uploads', img_filename), 'wb') as img_f:
                    img_f.write(raw)

        # Vision analysis only (no sensor text report generated)
        vision_data = None; vision_model = None
        if has_image:
            try:
                vision_raw, vision_model = call_gemini(build_vision_prompt(machine_type), image_b64, image_mime)
                clean = vision_raw.strip()
                if clean.startswith("```"): clean = clean.split("```")[1].lstrip("json").strip()
                vision_data = json.loads(clean)
            except json.JSONDecodeError:
                vision_data = {"overall_visual_summary": vision_raw, "defects_found": [], "manager_actions": [], "machine_condition": "UNKNOWN"}
            except Exception as e:
                vision_data = {"overall_visual_summary": f"Vision analysis error: {str(e)}", "defects_found": [], "manager_actions": [], "machine_condition": "UNKNOWN"}

        # NOTE: build_sensor_prompt and the ai_report call are removed.
        # The sensor analysis report card has been removed from the frontend.
        model_used = vision_model or (Config.MODELS[0] if Config.GEMINI_KEYS else 'gemini')

        sensor_display = {k:{'label':cfg['sensors'][k]['label'],'unit':cfg['sensors'][k]['unit']}
                          for k in sensor_keys if k in cfg['sensors']}

        # Save report to SQLite database
        report_id = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO reports (machine_type, health_score, risk_level, sensor_data, image_path, vision_data, recommendations)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                machine_type,
                sa['score'],
                sa['risk_level'],
                json.dumps(sensor_data),
                image_path,
                json.dumps(vision_data) if vision_data else None,
                json.dumps(recs)
            ))
            conn.commit()
            report_id = cursor.lastrowid
            conn.close()
        except Exception as db_err:
            print(f"⚠️ Database error saving report: {db_err}")

        return jsonify({
            'success':True, 'machine_type':machine_type,
            'health_score':sa['score'], 'risk_level':sa['risk_level'],
            'crit_count':sa['crit_count'], 'warn_count':sa['warn_count'],
            'statuses':sa['statuses'], 'issues':sa['issues'],
            'recommendations':recs, 'ai_report': '',
            'sensor_data':sensor_data, 'sensor_display':sensor_display,
            'has_image':has_image, 'model_used':model_used,
            'vision_data':vision_data, 'vision_model':vision_model,
            'report_id': report_id
        })

    except RuntimeError as e:
        return jsonify({'error':str(e)}), 503
    except Exception as e:
        return jsonify({'error':f'Analysis failed: {str(e)}'}), 500

@app.route('/reports')
def reports_page():
    return render_template('reports.html')

@app.route('/api/reports')
def get_reports_list():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT id, timestamp, machine_type, health_score, risk_level FROM reports ORDER BY id DESC')
        rows = cursor.fetchall()
        conn.close()
        return jsonify([dict(row) for row in rows])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def get_previous_report(machine_type, report_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, timestamp, health_score, risk_level, vision_data 
            FROM reports 
            WHERE machine_type = ? AND id < ? 
            ORDER BY id DESC 
            LIMIT 1
        ''', (machine_type, report_id))
        row = cursor.fetchone()
        conn.close()
        if row:
            res = dict(row)
            if res['vision_data']:
                res['vision_data'] = json.loads(res['vision_data'])
            return res
    except Exception as e:
        print(f"⚠️ Error getting previous report: {e}")
    return None

@app.route('/api/reports/<int:report_id>')
def get_report_details(report_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM reports WHERE id = ?', (report_id,))
        row = cursor.fetchone()
        conn.close()
        if not row:
            return jsonify({'error': 'Report not found'}), 404
        
        report = dict(row)
        report['sensor_data'] = json.loads(report['sensor_data'])
        report['recommendations'] = json.loads(report['recommendations'])
        if report['vision_data']:
            report['vision_data'] = json.loads(report['vision_data'])
            
        # Get previous condition
        prev = get_previous_report(report['machine_type'], report_id)
        report['previous_report'] = prev
        
        # We also need sensor configuration for display (labels, units) to render properly
        cfg = get_cfg(report['machine_type'])
        report['sensor_display'] = {k: {'label': s['label'], 'unit': s['unit'], 'icon': s['icon'], 'safe': s['safe'], 'warn': s['warn'], 'crit': s['crit']}
                                    for k, s in cfg['sensors'].items()}
        
        return jsonify(report)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/reports/<int:report_id>', methods=['DELETE'])
def delete_report(report_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT image_path FROM reports WHERE id = ?', (report_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return jsonify({'error': 'Report not found'}), 404
        
        image_path = row['image_path']
        
        # Delete from DB
        cursor.execute('DELETE FROM reports WHERE id = ?', (report_id,))
        conn.commit()
        conn.close()
        
        # Delete image from disk if exists
        if image_path:
            full_path = os.path.join('static', image_path)
            if os.path.exists(full_path):
                try:
                    os.remove(full_path)
                except Exception as file_err:
                    print(f"⚠️ Could not delete image file {full_path}: {file_err}")
                    
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/health')
def health_check():
    return jsonify({'status':'online','service':'IndustrialIQ','version':'4.0.0',
                    'keys_loaded':len(Config.GEMINI_KEYS),'models':Config.MODELS})

if __name__ == '__main__':
    os.makedirs('uploads', exist_ok=True)
    os.makedirs(os.path.join('static', 'uploads'), exist_ok=True)
    init_db()
    print(f"[*] IndustrialIQ v4 -- {len(Config.GEMINI_KEYS)} Gemini key(s) loaded")
    app.run(debug=True, host='0.0.0.0', port=5000)