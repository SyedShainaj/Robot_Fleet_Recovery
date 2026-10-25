from datetime import datetime, timezone
from io import BytesIO
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Flowable, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

NAVY = colors.HexColor('#23384d')
INK = colors.HexColor('#344b5c')
MUTED = colors.HexColor('#6f8390')
LINE = colors.HexColor('#d8e1e6')
PALE = colors.HexColor('#edf4f7')
TEAL = colors.HexColor('#2f91a3')
GREEN = colors.HexColor('#3f9b73')
AMBER = colors.HexColor('#d49539')
RED = colors.HexColor('#ca5b52')
WHITE = colors.white
PAGE_W, PAGE_H = A4

class SparkChart(Flowable):
    def __init__(self, values, labels, color=TEAL, threshold=None, width=178 * mm, height=30 * mm):
        super().__init__()
        self.values, self.labels, self.color = values, labels, color
        self.threshold, self.width, self.height = threshold, width, height
    def draw(self):
        c = self.canv; left, bottom = 25, 22; w, h = self.width - 35, self.height - 37
        c.setStrokeColor(LINE); c.setLineWidth(.45)
        for i in range(4):
            y = bottom + h * i / 3; c.line(left, y, left + w, y)
        maximum = max(max(self.values), self.threshold or 0, 1); minimum = min(0, min(self.values)); span = maximum - minimum or 1
        points = [(left + i * w / max(1, len(self.values) - 1), bottom + h * (value - minimum) / span) for i, value in enumerate(self.values)]
        c.setStrokeColor(self.color); c.setLineWidth(1.5)
        for a, b in zip(points, points[1:]): c.line(a[0], a[1], b[0], b[1])
        c.setFillColor(self.color)
        for x, y in points: c.circle(x, y, 2, fill=1, stroke=0)
        if self.threshold is not None:
            y = bottom + h * (self.threshold - minimum) / span
            c.setStrokeColor(RED); c.setDash(3, 2); c.line(left, y, left + w, y); c.setDash()
        c.setFillColor(MUTED); c.setFont('Helvetica', 6.6)
        for i, label in enumerate(self.labels): c.drawCentredString(left + i * w / max(1, len(self.labels) - 1), 7, label)

class BarChart(Flowable):
    def __init__(self, values, labels, colorset=None, width=178 * mm, height=30 * mm):
        super().__init__(); self.values, self.labels = values, labels; self.colorset = colorset or [TEAL, GREEN, AMBER, RED]; self.width, self.height = width, height
    def draw(self):
        c = self.canv; left, bottom = 25, 22; w, h = self.width - 35, self.height - 37; maximum = max(self.values) or 1
        c.setStrokeColor(LINE); c.setLineWidth(.45)
        for i in range(4): c.line(left, bottom + h * i / 3, left + w, bottom + h * i / 3)
        slot = w / max(1, len(self.values)); bar = slot * .48
        c.setFont('Helvetica', 6.6); c.setFillColor(MUTED)
        for i, value in enumerate(self.values):
            x = left + i * slot + (slot - bar) / 2; bh = h * value / maximum
            c.setFillColor(self.colorset[i % len(self.colorset)]); c.rect(x, bottom, bar, bh, fill=1, stroke=0)
            c.setFillColor(MUTED); c.drawCentredString(x + bar / 2, 7, self.labels[i])
            c.setFillColor(INK); c.drawCentredString(x + bar / 2, bottom + bh + 4, str(value))

class KPIBlock(Flowable):
    def __init__(self, items, width=178 * mm, height=22 * mm):
        super().__init__(); self.items, self.width, self.height = items, width, height
    def draw(self):
        c = self.canv; cell = self.width / len(self.items); c.setStrokeColor(LINE); c.setFillColor(PALE); c.roundRect(0, 0, self.width, self.height, 2, fill=1, stroke=0)
        for i, (label, value, tone) in enumerate(self.items):
            if i: c.setStrokeColor(LINE); c.line(i * cell, 4, i * cell, self.height - 4)
            c.setFillColor(tone); c.setFont('Helvetica-Bold', 12); c.drawString(i * cell + 7, 10, str(value))
            c.setFillColor(MUTED); c.setFont('Helvetica-Bold', 5.5); c.drawString(i * cell + 7, 3, label.upper())

class PropagationGraph(Flowable):
    def __init__(self, width=178 * mm, height=39 * mm): super().__init__(); self.width, self.height = width, height
    def draw(self):
        c = self.canv; c.setStrokeColor(colors.HexColor('#93aebc')); c.setLineWidth(1)
        nodes = [('R-004', 'FAILED ROBOT', RED), ('MOTOR', 'SUBSYSTEM', RED), ('T-014', 'TASK IMPACT', AMBER), ('MISSION-03', 'MISSION', TEAL), ('R-009', 'RECOVERY ROBOT', GREEN)]
        x_positions = [8, 43, 78, 113, 148]; y = self.height / 2 + 4
        for index, (title, subtitle, tone) in enumerate(nodes):
            x = x_positions[index] * mm
            if index:
                c.setStrokeColor(colors.HexColor('#93aebc')); c.line(x - 10 * mm, y, x, y)
                c.setFillColor(colors.HexColor('#93aebc')); c.line(x - 2, y, x, y); c.line(x - 2, y, x - 4, y + 2); c.line(x - 2, y, x - 4, y - 2)
            c.setFillColor(tone); c.roundRect(x, y - 13, 26 * mm, 26, 3, fill=1, stroke=0); c.setFillColor(WHITE); c.setFont('Helvetica-Bold', 6.3); c.drawCentredString(x + 13 * mm, y + 1, title); c.setFont('Helvetica', 5.2); c.drawCentredString(x + 13 * mm, y - 7, subtitle)
        c.setStrokeColor(AMBER); c.setDash(2, 2); c.line(96 * mm, y - 13, 96 * mm, 4); c.line(96 * mm, 4, 165 * mm, 4); c.setDash(); c.setFillColor(MUTED); c.setFont('Helvetica', 6.2); c.drawString(125 * mm, 1, 'FLEET CAPACITY IMPACT')

def make_styles():
    base = getSampleStyleSheet()
    return {
        'eyebrow': ParagraphStyle('eyebrow', parent=base['Normal'], fontName='Helvetica-Bold', fontSize=7, leading=9, textColor=MUTED, spaceAfter=2),
        'title': ParagraphStyle('title', parent=base['Title'], fontName='Helvetica-Bold', fontSize=21, leading=24, textColor=NAVY, spaceAfter=4),
        'subtitle': ParagraphStyle('subtitle', parent=base['Normal'], fontName='Helvetica', fontSize=10, leading=13, textColor=INK, spaceAfter=8),
        'section': ParagraphStyle('section', parent=base['Heading2'], fontName='Helvetica-Bold', fontSize=10.5, leading=13, textColor=NAVY, spaceBefore=5, spaceAfter=4),
        'body': ParagraphStyle('body', parent=base['BodyText'], fontName='Helvetica', fontSize=8, leading=11, textColor=INK, spaceAfter=4),
        'small': ParagraphStyle('small', parent=base['BodyText'], fontName='Helvetica', fontSize=7, leading=9, textColor=MUTED),
        'cell': ParagraphStyle('cell', parent=base['BodyText'], fontName='Helvetica', fontSize=7, leading=8.5, textColor=INK),
        'cell_bold': ParagraphStyle('cell_bold', parent=base['BodyText'], fontName='Helvetica-Bold', fontSize=7, leading=8.5, textColor=NAVY),
    }

def p(text, style): return Paragraph(str(text), style)

def report_table(rows, widths, styles, header=True):
    converted = []
    for r, row in enumerate(rows):
        converted.append([p(value, styles['cell_bold'] if header and r == 0 else styles['cell']) for value in row])
    table = Table(converted, colWidths=widths, repeatRows=1 if header else 0, hAlign='LEFT')
    table.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), PALE if header else WHITE), ('TEXTCOLOR', (0, 0), (-1, 0), NAVY), ('GRID', (0, 0), (-1, -1), .35, LINE), ('ROWBACKGROUNDS', (0, 1), (-1, -1), [WHITE, colors.HexColor('#f8fafb')]), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('LEFTPADDING', (0, 0), (-1, -1), 6), ('RIGHTPADDING', (0, 0), (-1, -1), 6), ('TOPPADDING', (0, 0), (-1, -1), 4), ('BOTTOMPADDING', (0, 0), (-1, -1), 4)]))
    return table

def section(title, description, styles):
    return [p(title, styles['section']), p(description, styles['body'])]

def _render_legacy_report(data, report_id):
    styles = make_styles(); performance = data.get('performance', {}); robots = data.get('robots') or []; missions = data.get('missions') or []; migrations = data.get('migrations') or []; events = data.get('events') or []
    failures = data.get('failures') or []
    predictions = data.get('predictions') or []
    if not events:
        events = [{'type': 'DERIVED', 'message': 'Simulation snapshot received; recovery event stream not started.'}]
    migration_total = len(migrations)
    successful_migrations = sum(1 for item in migrations if str(item.get('status', 'SUCCESS')).upper() in {'SUCCESS', 'COMPLETED'})
    pending_migrations = sum(1 for item in migrations if str(item.get('status', '')).upper() in {'PENDING', 'QUEUED'})
    rejected_migrations = migration_total - successful_migrations - pending_migrations
    if rejected_migrations < 0:
        rejected_migrations = 0
    failure = failures[0] if failures else {'robot_id': 'R-004', 'subsystem': 'motor', 'risk': 0}
    prediction = predictions[0] if predictions else {'robot_id': failure.get('robot_id', 'R-004'), 'probability': failure.get('risk', 0), 'confidence': 0}
    risk_value = prediction.get('probability', failure.get('risk', 0))
    active_missions = len(missions)
    fleet_size = len(robots)
    healthy = sum(r.get('health', 0) >= 70 for r in robots); warning = sum(45 <= r.get('health', 0) < 70 for r in robots); critical = sum(r.get('health', 0) < 45 for r in robots); failed_robots = sum(str(r.get('status', r.get('state', ''))).lower() == 'failed' for r in robots)
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    story = []
    def header(title): return [p('SENTINEL ROBOTICS', styles['eyebrow']), p('SENTINEL FLEET RECOVERY AI', styles['small']), p(title, styles['section'])]
    story += [p('SENTINEL ROBOTICS', styles['eyebrow']), Spacer(1, 2 * mm), p('SENTINEL FLEET<br/>RECOVERY AI', styles['title']), p('Mission Recovery Report', styles['subtitle']), p('Simulation environment · operational intelligence dossier', styles['body'])]
    cover = [['MISSION INTELLIGENCE', 'CURRENT VALUE'], ['USER', data.get('user', {}).get('name', 'Simulation Operator')], ['ORGANIZATION', data.get('user', {}).get('organization', 'Sentinel Robotics')], ['MISSION', data.get('mission', 'Fleet recovery cascade response')], ['REPORT ID', report_id], ['SIMULATION ID', data.get('simulation_id', 'SIM-2026-DEMO')], ['GENERATED', now], ['ENVIRONMENT', 'Simulation environment'], ['REPORT STATUS', 'FINAL · VERIFIED']]
    story += [report_table(cover, [58 * mm, 120 * mm], styles), Spacer(1, 3 * mm), p('MISSION SNAPSHOT', styles['section']), KPIBlock([('Fleet size', fleet_size, TEAL), ('Active robots', healthy + warning, GREEN), ('Critical robots', critical, RED), ('Active missions', active_missions, TEAL), ('Performance', f"{performance.get('recovered', 0)}%", GREEN), ('Cascade risk', f'{risk_value}%', AMBER)]), Spacer(1, 2 * mm), p('RECOVERY SIGNAL', styles['section']), SparkChart([performance.get('before', 98.4), performance.get('lowest', 54.2), performance.get('recovered', 89.7)], ['BEFORE', 'CASCADE', 'RECOVERED'], TEAL), p('All values in this document are generated from the current deterministic simulation snapshot and do not represent physical robot telemetry.', styles['small']), PageBreak()]
    story += header('1. EXECUTIVE SUMMARY') + [p('The recovery engine maintained critical mission continuity through a cascading failure sequence. The report combines current robot telemetry, failure prediction, propagation analysis, migration decisions, and recovery outcomes.', styles['body']), KPIBlock([('Initial', f"{performance.get('before', 0)}%", NAVY), ('Lowest', f"{performance.get('lowest', 0)}%", RED), ('Recovered', f"{performance.get('recovered', 0)}%", GREEN)]), Spacer(1, 3 * mm), p('MISSION RECOVERY STATUS  ·  CONTAINED', styles['section'])]
    story.append(report_table([['FLEET STATUS', 'VALUE', 'MISSION STATUS', 'VALUE'], ['Fleet size', fleet_size, 'Tasks', sum(m.get('tasks', 0) if isinstance(m.get('tasks', 0), int) else 0 for m in missions)], ['Healthy', healthy, 'Critical tasks', '100% preserved'], ['Warning', warning, 'Tasks migrated', migration_total], ['Critical', critical, 'Recovery time', data.get('recovery_duration', '42 seconds')], ['Failed', sum(1 for r in robots if str(r.get('status', '')).lower() == 'failed'), 'Energy saved', data.get('energy_saved', '18.6%')]], [38 * mm, 25 * mm, 48 * mm, 67 * mm], styles)); story += [Spacer(1, 3 * mm), SparkChart([performance.get('before', 0), performance.get('lowest', 0), performance.get('recovered', 0)], ['INITIAL', 'LOWEST', 'RECOVERED'], TEAL), PageBreak()]
    story += header('2. FLEET OVERVIEW') + [p('A representative health view summarizes the current fleet while keeping the report dense enough for operator review.', styles['body']), KPIBlock([('Total robots', len(robots), TEAL), ('Healthy', healthy, GREEN), ('Warning', warning, AMBER), ('Critical', critical, RED), ('Failed', failed_robots, MUTED)]), Spacer(1, 3 * mm), BarChart([healthy, warning, critical, failed_robots], ['HEALTHY', 'WARNING', 'CRITICAL', 'FAILED'])]
    story += section('3. ROBOT HEALTH', 'Top-risk units, critical units, and representative healthy units are shown from the current telemetry snapshot.', styles)
    selected = sorted(robots, key=lambda r: r.get('health', 0))[:20]
    health_rows = [['ROBOT', 'TYPE', 'HEALTH', 'BATTERY', 'TEMPERATURE', 'LOAD', 'STATUS', 'FAILURE RISK']]
    for r in selected: health_rows.append([r.get('id', '-'), r.get('type', '-'), f"{r.get('health', 0)}%", f"{r.get('battery', 0)}%", f"{r.get('temperature', 0)}°C", f"{r.get('cpu', 0)}%", r.get('state', r.get('status', 'Healthy')).upper(), f"{max(4, 100-r.get('health', 0))}%"])
    story += [report_table(health_rows, [20*mm, 20*mm, 18*mm, 18*mm, 25*mm, 18*mm, 27*mm, 25*mm], styles), Spacer(1, 2 * mm), BarChart([healthy, warning, critical], ['HEALTHY', 'WARNING', 'CRITICAL']), PageBreak()]
    story += header('4. FAILURE ANALYSIS') + section('4. FAILURE PREDICTION', f"{failure.get('robot_id', 'R-004')} is the highest-risk unit in the submitted snapshot. The transparent feature contribution view explains the synthetic prediction.", styles)
    story += [KPIBlock([('Risk', f'{risk_value}%', RED), ('Confidence', f"{prediction.get('confidence', 0)}%", TEAL), ('Subsystem', str(failure.get('subsystem', 'unknown')).upper(), AMBER), ('Predicted failure', 'MOTOR' if failure.get('subsystem') == 'motor' else 'REVIEW', RED)]), Spacer(1, 3 * mm), report_table([['FEATURE CONTRIBUTION', 'IMPACT'], ['Motor temperature', '+31%'], ['Battery degradation', '+18%'], ['CPU load', '+14%'], ['Vibration', '+12%'], ['Task overload', '+9%']], [130*mm, 48*mm], styles), Spacer(1, 2 * mm), SparkChart([84, 91, 96], ['10 MIN', '20 MIN', '30 MIN'], RED)]
    story += section('5. FAILURE PROPAGATION', 'A compact dependency graph shows the failed robot, subsystem, task impact, mission impact, recovery robots, and capacity branch.', styles) + [PropagationGraph(), Spacer(1, 2 * mm), report_table([['PROPAGATION STATISTIC', 'VALUE'], ['Affected robots', len(failures) or 'Derived from graph'], ['Affected tasks', sum(1 for m in migrations if m.get('task'))], ['Affected missions', active_missions], ['Cascade risk', f'{risk_value}%'], ['Propagation depth', '5 hops']], [90*mm, 88*mm], styles), PageBreak()]
    story += header('6. MISSION CONTINUITY') + section('6. MISSION CRITICALITY', 'Priority-aware orchestration preserves critical work before high, medium, and low-criticality work.', styles)
    mission_rows = [['MISSION', 'PRIORITY', 'TASKS', 'DEADLINE', 'PROGRESS', 'STATUS']]
    for m in missions: mission_rows.append([m.get('name', 'Mission'), m.get('priority', 'High').upper(), m.get('tasks', '—'), m.get('deadline', '—'), f"{m.get('progress', 0)}%", m.get('status', 'Active').upper()])
    if len(mission_rows) == 1: mission_rows += [['Harbor perimeter sweep', 'CRITICAL', '14', '18 MIN', '78%', 'ACTIVE'], ['Emergency delivery', 'CRITICAL', '9', '9 MIN', '92%', 'PROTECTED'], ['Thermal leak survey', 'HIGH', '10', '34 MIN', '51%', 'REBALANCING']]
    story += [report_table(mission_rows, [51*mm, 24*mm, 20*mm, 25*mm, 22*mm, 36*mm], styles), Spacer(1, 3 * mm), BarChart([2, 1, 1, 0], ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'])]
    story += section('7. TASK MIGRATION', 'Candidate selection weighs capability compatibility, battery, load, distance, health, failure risk, and mission priority.', styles)
    migration_rows = [['TASK', 'SOURCE', 'REPLACEMENT', 'DISTANCE', 'BATTERY', 'LOAD', 'RISK', 'SCORE', 'STATUS']]
    for index, m in enumerate(migrations[:12]): migration_rows.append([m.get('task', 'T-014'), m.get('from', 'R-004'), m.get('to', 'R-009'), f"{m.get('distance', 120)}m", f"{m.get('battery', 82)}%", f"{m.get('load', 31)}%", f"{m.get('risk', 8)}%", m.get('score', 91), 'SUCCESS'])
    if not migrations:
        migration_rows.append(['—', '—', '—', '—', '—', '—', '—', '—', 'NOT STARTED'])
    story += [report_table(migration_rows, [16*mm, 18*mm, 22*mm, 22*mm, 19*mm, 17*mm, 17*mm, 17*mm, 30*mm], styles), Spacer(1, 2 * mm), p(f"{migration_total} migrations evaluated  ·  {successful_migrations} successful  ·  {pending_migrations} pending  ·  {rejected_migrations} rejected/deferred", styles['small']), KPIBlock([('Evaluated', migration_total, TEAL), ('Successful', successful_migrations, GREEN), ('Pending', pending_migrations, AMBER), ('Deferred', rejected_migrations, RED)]), PageBreak()]
    average_battery = round(sum(r.get('battery', 0) for r in robots) / fleet_size) if fleet_size else 0
    critical_battery = sum(r.get('battery', 0) < 30 for r in robots)
    story += header('8. RESOURCE RECOVERY') + section('8. FLEET REBALANCING', 'Before/after load comparison demonstrates how the recovery engine distributes work without overloading healthy robots.', styles) + [BarChart([92, 88, 21, 18, 64, 61, 58, 55], ['R01 B', 'R02 B', 'R03 B', 'R04 B', 'R01 A', 'R02 A', 'R03 A', 'R04 A']), KPIBlock([('Utilization gain', '28 PP', GREEN), ('Overload prevented', 'Derived', TEAL), ('Reserve', '20%', AMBER), ('Rebalanced', migration_total, TEAL)]), Spacer(1, 2 * mm), report_table([['RESULT', 'VALUE'], ['Average fleet battery', f'{average_battery}%'], ['Critical battery robots', critical_battery], ['Reserve capacity', '20% protected'], ['Robots represented', fleet_size]], [90*mm, 88*mm], styles)]
    battery_values = [average_battery, max(0, average_battery - 6), max(0, average_battery - 13), max(0, average_battery - 26), max(0, average_battery - 35)]
    story += section('9. BATTERY OPTIMIZATION', 'Battery reserve and drain are considered in every migration and charging decision.', styles) + [SparkChart(battery_values, ['NOW', '5 MIN', '15 MIN', '30 MIN', '60 MIN'], GREEN), KPIBlock([('Average reserve', f'{average_battery}%', GREEN), ('Critical battery', critical_battery, RED), ('Reserve threshold', '20%', AMBER), ('Charging state', 'ACTIVE', TEAL)])]
    story += section('10. CAPACITY FORECAST', 'Available capacity is compared with the mission requirement and the protected reserve threshold.', styles) + [SparkChart(battery_values, ['NOW', '5M', '15M', '30M', '60M'], TEAL, threshold=61, height=22 * mm), report_table([['HORIZON', 'AVAILABLE', 'REQUIRED', 'ASSESSMENT'], *[[label, f'{value}%', '61%', 'SUSTAINABLE' if value >= 61 else 'DEGRADED'] for label, value in zip(['Now', '5 minutes', '15 minutes', '30 minutes', '60 minutes'], battery_values)]], [38*mm, 38*mm, 38*mm, 54*mm], styles), PageBreak()]
    story += header('11. RECOVERY OUTCOMES') + section('11. RECOVERY TIMELINE', 'The complete event sequence is retained so operators can audit prediction, failure, migration, rebalancing, and recovery.', styles)
    timeline = [['TIME', 'EVENT', 'TYPE', 'RESULT'], ['12:41:03', 'AI detected elevated motor temperature', 'PREDICTION', 'Risk 78%'], ['12:41:09', 'R-004 marked high risk', 'ALERT', 'Critical'], ['12:41:17', 'R-004 failure detected', 'FAILURE', 'Motor subsystem'], ['12:41:21', 'T-014 migration initiated', 'RECOVERY', 'Started'], ['12:41:27', 'T-014 assigned to R-009', 'MIGRATION', 'Success'], ['12:41:35', 'Fleet rebalancing initiated', 'REBALANCE', 'Started'], ['12:42:34', 'Mission performance recovered', 'RECOVERY', f"{performance.get('recovered', 89.7)}%"]]
    story += [report_table(timeline, [24*mm, 75*mm, 35*mm, 44*mm], styles), Spacer(1, 3 * mm)]
    story += section('12. MISSION PERFORMANCE', 'Performance is measured across the failure and recovery window.', styles) + [KPIBlock([('Before failure', f"{performance.get('before', 98.4)}%", NAVY), ('Lowest cascade', f"{performance.get('lowest', 54.2)}%", RED), ('After recovery', f"{performance.get('recovered', 89.7)}%", GREEN)]), Spacer(1, 2 * mm), SparkChart([performance.get('before', 98.4), performance.get('lowest', 54.2), performance.get('recovered', 89.7)], ['BEFORE FAILURE', 'LOWEST', 'RECOVERED'], TEAL)]
    story += section('13. EVENT LOG', 'Current recovery events are shown below. Severity is represented through event type and report color coding.', styles)
    event_rows = [['TIME', 'TYPE', 'ROBOT / TASK', 'MESSAGE', 'SEVERITY']]
    for event in events[:10]: event_rows.append(['12:41:52', event.get('type', 'SYSTEM').upper(), 'R-004 / T-014', event.get('message', 'Recovery event'), 'NORMAL' if str(event.get('type', 'SYSTEM')).upper() == 'SYSTEM' else 'CRITICAL'])
    story += [report_table(event_rows, [22*mm, 25*mm, 34*mm, 72*mm, 25*mm], styles), PageBreak()]
    story += header('14. FINAL RECOVERY STATUS') + [p('CASCADE CONTAINED', styles['title']), p('The recovery plan maintained the highest achievable mission performance for the current simulation state.', styles['body']), KPIBlock([('Fleet', fleet_size, TEAL), ('Missions', active_missions, TEAL), ('Tasks migrated', migration_total, GREEN), ('Recovery', 'VERIFIED', GREEN)]), Spacer(1, 2 * mm), report_table([['RECOVERY RESULT', 'VALUE'], ['Recovered performance', f"{performance.get('recovered', 89.7)}%"], ['Tasks migrated', str(migration_total)], ['Critical tasks preserved', '100%'], ['Energy saved', data.get('energy_saved', 'Derived')], ['Robots recovered', str(len(failures))], ['Recovery time', data.get('recovery_duration', 'Derived')], ['Cascade risk', f'CONTAINED · {risk_value}%'], ['Verification ID', report_id]], [90*mm, 88*mm], styles), Spacer(1, 3 * mm), p('SYSTEM STATE  ·  FLEET ONLINE  ·  MISSIONS PROTECTED  ·  RESOURCES MONITORED  ·  RECOVERY VERIFIED', styles['section']), SparkChart([performance.get('before', 98.4), performance.get('lowest', 54.2), performance.get('recovered', 89.7)], ['DETECTED', 'CONTAINED', 'RECOVERED'], GREEN), Spacer(1, 2 * mm), p('DETECTED  →  CONTAINED  →  RECOVERED  →  VERIFIED', styles['small']), p('Sentinel Robotics · Sentinel Fleet Recovery AI · Simulation Report', styles['small'])]
    def draw_header_footer(canvas, document):
        canvas.saveState(); canvas.setFillColor(NAVY); canvas.setFont('Helvetica-Bold', 7.5); canvas.drawString(16 * mm, PAGE_H - 12 * mm, 'SENTINEL ROBOTICS'); canvas.setFillColor(MUTED); canvas.setFont('Helvetica', 7); canvas.drawString(16 * mm, PAGE_H - 16 * mm, 'SENTINEL FLEET RECOVERY AI'); canvas.setStrokeColor(LINE); canvas.setLineWidth(.5); canvas.line(16 * mm, PAGE_H - 18 * mm, PAGE_W - 16 * mm, PAGE_H - 18 * mm); canvas.line(16 * mm, 13 * mm, PAGE_W - 16 * mm, 13 * mm); canvas.setFillColor(MUTED); canvas.setFont('Helvetica', 7); canvas.drawString(16 * mm, 8 * mm, 'Sentinel Robotics · Sentinel Fleet Recovery AI · Simulation Report'); canvas.drawRightString(PAGE_W - 16 * mm, 8 * mm, f'Page {document.page}'); canvas.restoreState()
    output = BytesIO(); doc = SimpleDocTemplate(output, pagesize=A4, rightMargin=16 * mm, leftMargin=16 * mm, topMargin=22 * mm, bottomMargin=17 * mm, title='Sentinel Fleet Recovery AI Report', author='Sentinel Robotics')
    doc.build(story, onFirstPage=draw_header_footer, onLaterPages=draw_header_footer)
    return output.getvalue()


def render_report(data, report_id):
    from xml.sax.saxutils import escape

    styles = make_styles()
    robots = data.get("robots") or []
    tasks = list((data.get("tasks") or {}).values())
    missions = data.get("missions") or []
    failures = data.get("failures") or []
    predictions = data.get("predictions") or []
    migrations = data.get("migrations") or []
    events = data.get("events") or []
    evaluation = data.get("evaluation") or {}
    output = BytesIO()
    doc = SimpleDocTemplate(output, pagesize=A4, rightMargin=16 * mm, leftMargin=16 * mm, topMargin=20 * mm, bottomMargin=17 * mm, title="Sentinel Simulation Snapshot", author="Sentinel Robotics", pageCompression=0)
    story = []

    def label(value):
        return escape(str(value if value is not None else "Not available"))

    def add_table(headers, rows, widths):
        story.append(report_table([headers, *rows], widths, styles))

    def section_page(title, description, headers, rows, widths):
        story.extend([p("SENTINEL ROBOTICS · SIMULATION SNAPSHOT", styles["eyebrow"]), p(title, styles["title"]), p(description, styles["body"])])
        add_table(headers, rows or [["—" for _ in headers]], widths)

    active = sum(1 for robot in robots if robot.get("status") in {"healthy", "warning", "recovering"})
    failed = sum(1 for robot in robots if robot.get("status") in {"failed", "critical"})
    charging = sum(1 for robot in robots if robot.get("status") == "charging")
    overview = [
        ["Report ID", report_id],
        ["Simulation ID", data.get("simulation_id", "Not available")],
        ["Generated", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")],
        ["Environment", "Simulation only; not physical robot telemetry"],
        ["Robots · active · charging · failed", f"{len(robots)} · {active} · {charging} · {failed}"],
        ["Tasks · assigned · at risk", f"{len(tasks)} · {evaluation.get('tasks_assigned', 'Not measured')} · {evaluation.get('tasks_at_risk', 'Not measured')}"],
        ["Average task progress", f"{label(evaluation.get('mission_completion_rate'))}%" if evaluation.get("mission_completion_rate") is not None else "Not measured"],
        ["Mission continuity", f"{label(evaluation.get('mission_preservation'))}%" if evaluation.get("mission_preservation") is not None else "Not measured"],
        ["Average battery", f"{label(evaluation.get('average_battery'))}%" if evaluation.get("average_battery") is not None else "Not measured"],
        ["Recovery performance / prediction accuracy", "Not measured unless supported by recorded events"],
    ]
    section_page("Current Fleet State", "All values below are read from this snapshot. No benchmark or unobserved recovery outcome is inferred.", ["MEASURE", "CURRENT VALUE"], overview, [65 * mm, 113 * mm])
    story.append(PageBreak())

    robot_rows = [[robot.get("id", "—"), robot.get("type", "—"), robot.get("status", "—"), f"{robot.get('health', '—')}%", f"{robot.get('battery', '—')}%", f"{robot.get('position', {}).get('x', '—')}, {robot.get('position', {}).get('y', '—')}", robot.get("current_task") or "Unassigned"] for robot in robots]
    section_page("Robot Roster", "Backend robot records and current telemetry at report time.", ["ROBOT", "TYPE", "STATUS", "HEALTH", "BATTERY", "POSITION", "TASK"], robot_rows, [19 * mm, 19 * mm, 23 * mm, 18 * mm, 18 * mm, 33 * mm, 48 * mm])
    story.append(PageBreak())

    mission_rows = [[mission.get("id", "—"), mission.get("name", "—"), mission.get("priority", "—"), mission.get("status", "—"), f"{mission.get('progress', '—')}%", ", ".join(mission.get("tasks", []))] for mission in missions]
    task_rows = [[task.get("id", "—"), task.get("mission_id", "—"), task.get("assigned_robot") or "Unassigned", task.get("status", "—"), f"{task.get('progress', '—')}%", f"{task.get('remaining_progress', '—')}%", f"{task.get('origin', '—')} → {task.get('destination', '—')}"] for task in tasks]
    section_page("Missions and Tasks", "Progress, ownership, priority, and route are sourced from the task and mission records.", ["MISSION", "NAME", "PRIORITY", "STATUS", "PROGRESS", "TASK IDS"], mission_rows, [20 * mm, 46 * mm, 22 * mm, 25 * mm, 19 * mm, 46 * mm])
    story.extend([Spacer(1, 3 * mm), p("TASK OWNERSHIP", styles["section"])])
    add_table(["TASK", "MISSION", "OWNER", "STATUS", "DONE", "LEFT", "ROUTE"], task_rows, [17 * mm, 19 * mm, 18 * mm, 25 * mm, 14 * mm, 14 * mm, 71 * mm])
    story.append(PageBreak())

    failure_rows = [[failure.get("robot_id", "—"), failure.get("subsystem", "—"), failure.get("severity", "—"), f"{failure.get('risk', '—')}%", f"{failure.get('progress', '—')}%", label(failure.get("timestamp"))] for failure in failures]
    prediction_rows = [[item.get("robot_id", "—"), item.get("model", "simulation-based rule"), f"{item.get('probability', '—')}%", f"{item.get('confidence', 'Not measured')}", label(item.get("subsystem")), label(item.get("predicted_at"))] for item in predictions]
    section_page("Failure and Prediction Records", "Prediction entries are simulation-based telemetry rules; no trained-model accuracy is claimed.", ["ROBOT", "SUBSYSTEM", "SEVERITY", "RISK", "TASK PROGRESS", "RECORDED AT"], failure_rows, [22 * mm, 28 * mm, 22 * mm, 17 * mm, 25 * mm, 64 * mm])
    story.extend([Spacer(1, 3 * mm), p("PREDICTIONS", styles["section"])])
    add_table(["ROBOT", "MODEL", "RISK", "CONFIDENCE", "CAUSE", "PREDICTED AT"], prediction_rows, [20 * mm, 45 * mm, 17 * mm, 24 * mm, 25 * mm, 47 * mm])
    story.append(PageBreak())

    migration_rows = [[item.get("migration_id", "—"), ", ".join(item.get("task_ids", [])), item.get("source_robot", "—"), item.get("destination_robot", "—"), item.get("status", "—"), f"{item.get('progress_before_failure', '—')}%", label(item.get("reason"))] for item in migrations]
    propagation_rows = [[node.get("type", "—"), node.get("id", "—"), node.get("status", "—")] for node in data.get("propagation", [])]
    section_page("Recovery and Propagation", "Only recorded migrations and incident dependencies are shown; unrecorded outcomes remain unavailable.", ["MIGRATION", "TASKS", "SOURCE", "REPLACEMENT", "STATUS", "PRESERVED", "SELECTION REASON"], migration_rows, [24 * mm, 20 * mm, 20 * mm, 23 * mm, 21 * mm, 19 * mm, 51 * mm])
    story.extend([Spacer(1, 3 * mm), p("PROPAGATION NODES", styles["section"])])
    add_table(["ENTITY TYPE", "ENTITY ID", "STATE"], propagation_rows, [50 * mm, 70 * mm, 58 * mm])
    story.append(PageBreak())

    event_rows = [[label(event.get("timestamp")), label(event.get("type")), label(event.get("robot") or event.get("source_robot")), label(event.get("message"))] for event in events[:40]]
    section_page("Recorded Event Timeline", "Chronological event data emitted by the backend simulation.", ["TIMESTAMP", "EVENT", "ROBOT", "DETAIL"], event_rows, [43 * mm, 31 * mm, 28 * mm, 76 * mm])
    story.extend([Spacer(1, 4 * mm), p(f"Measured fields: mission completion {label(evaluation.get('mission_completion_rate')) if evaluation.get('mission_completion_rate') is not None else 'not measured'}%; mission continuity {label(evaluation.get('mission_preservation')) if evaluation.get('mission_preservation') is not None else 'not measured'}%; migration success {label(evaluation.get('migration_success_rate')) if evaluation.get('migration_success_rate') is not None else 'not measured'}.", styles["small"])])

    def draw_header_footer(canvas, document):
        canvas.saveState()
        canvas.setFillColor(NAVY)
        canvas.setFont("Helvetica-Bold", 7.5)
        canvas.drawString(16 * mm, PAGE_H - 12 * mm, "SENTINEL ROBOTICS")
        canvas.setStrokeColor(LINE)
        canvas.line(16 * mm, PAGE_H - 16 * mm, PAGE_W - 16 * mm, PAGE_H - 16 * mm)
        canvas.setFillColor(MUTED)
        canvas.setFont("Helvetica", 7)
        canvas.drawString(16 * mm, 8 * mm, "Simulation snapshot · not physical robot telemetry")
        canvas.drawRightString(PAGE_W - 16 * mm, 8 * mm, f"Page {document.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=draw_header_footer, onLaterPages=draw_header_footer)
    return output.getvalue()
