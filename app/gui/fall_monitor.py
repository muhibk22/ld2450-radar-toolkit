"""
Separate window for monitoring Fall Detection state, alert history, and statistics.
Supports two-stage alerts: PRE_ALERT (yellow) and CONFIRMED (red).
"""

from PySide6.QtCore import Qt, Slot, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QProgressBar, QFrame,
    QTextEdit, QSplitter, QTabWidget, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QFileDialog, QMessageBox, QComboBox
)
from PySide6.QtGui import QFont
from PySide6.QtMultimedia import QSoundEffect
from PySide6.QtCore import QUrl
import os
import csv
import json
from pathlib import Path
from ..ml.model_comparison import MODEL_NAMES, time_label

class FallMonitorWindow(QWidget):
    """
    A dedicated floating window to display live fall detection state, 
    two-stage alert visualization (pre-alert + confirmed), alert history, and fall counts.
    """
    comparison_profile_changed = Signal(str)
    validation_warnings_acknowledged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Fall Detection Monitor")
        self.resize(860, 660)
        self._comparison_revision = -1
        self._comparison_events = []
        self._event_signature = None
        
        # We want it to be a floating tool window if parent is set
        if parent:
            self.setWindowFlags(Qt.WindowType.Tool)

        self.fall_count = 0
        self.is_falling = False
        self._current_stage = "normal"
        
        # Debounce logic so one fall event doesn't increment count 20 times per second
        self.cooldown_frames = 0
        self._current_stage_key = None
        
        # Sound alert (optional)
        self._sound_enabled = True
        self._sound_effect = None
        
        self._setup_ui()

    def _setup_ui(self):
        root = QVBoxLayout(self)
        self.tabs = QTabWidget()
        root.addWidget(self.tabs)
        original_page = QWidget()
        self.tabs.addTab(original_page, 'Ensemble monitor')
        layout = QVBoxLayout(original_page)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Title
        title = QLabel("AI Fall Monitor")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        layout.addWidget(title)
        
        # Current State (supports NORMAL / PRE-ALERT / CONFIRMED)
        self.lbl_state = QLabel("NORMAL")
        self.lbl_state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_state.setFont(QFont("Segoe UI", 22, QFont.Weight.ExtraBold))
        self.lbl_state.setMinimumHeight(60)
        self._set_state_style("normal")
        layout.addWidget(self.lbl_state)
        
        # Probability Bar
        prob_layout = QVBoxLayout()
        prob_label = QLabel("Live Fall Probability:")
        prob_label.setFont(QFont("Segoe UI", 10))
        self.bar_prob = QProgressBar()
        self.bar_prob.setRange(0, 100)
        self.bar_prob.setValue(0)
        self.bar_prob.setTextVisible(True)
        self.bar_prob.setStyleSheet("""
            QProgressBar {
                border: 2px solid #334155;
                border-radius: 5px;
                text-align: center;
                color: white;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background-color: #10B981;
                width: 10px;
            }
        """)
        prob_layout.addWidget(prob_label)
        prob_layout.addWidget(self.bar_prob)
        layout.addLayout(prob_layout)
        
        # Fall Count
        count_layout = QHBoxLayout()
        lbl_count_title = QLabel("Confirmed Falls:")
        lbl_count_title.setFont(QFont("Segoe UI", 14))
        self.lbl_count_val = QLabel("0")
        self.lbl_count_val.setFont(QFont("Segoe UI", 20, QFont.Weight.Bold))
        self.lbl_count_val.setStyleSheet("color: #F43F5E;")
        count_layout.addWidget(lbl_count_title)
        count_layout.addWidget(self.lbl_count_val)
        layout.addLayout(count_layout)
        
        # Alert History Log
        history_label = QLabel("Alert History:")
        history_label.setFont(QFont("Segoe UI", 10))
        layout.addWidget(history_label)
        
        self.txt_history = QTextEdit()
        self.txt_history.setReadOnly(True)
        self.txt_history.setMaximumHeight(150)
        self.txt_history.setFont(QFont("Consolas", 9))
        self.txt_history.setStyleSheet("""
            QTextEdit {
                background-color: #1E293B;
                color: #94A3B8;
                border: 1px solid #334155;
                border-radius: 4px;
                padding: 4px;
            }
        """)
        layout.addWidget(self.txt_history)
        
        # Control Buttons
        btn_layout = QHBoxLayout()
        
        self.btn_reset = QPushButton("Reset Count")
        self.btn_reset.setStyleSheet("background-color: #334155; color: white; padding: 8px; font-weight: bold;")
        self.btn_reset.clicked.connect(self.reset_count)
        btn_layout.addWidget(self.btn_reset)
        
        self.btn_sound = QPushButton("🔔 Sound: ON")
        self.btn_sound.setStyleSheet("background-color: #334155; color: white; padding: 8px; font-weight: bold;")
        self.btn_sound.clicked.connect(self._toggle_sound)
        btn_layout.addWidget(self.btn_sound)
        
        layout.addLayout(btn_layout)
        
        self.setStyleSheet("""
            QWidget {
                background-color: #0F172A;
                color: #F8FAFC;
                font-family: 'Segoe UI';
            }
        """)
        self._setup_comparison_tab()
        self.tabs.setCurrentIndex(1)

    def _setup_comparison_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        self.profile_combo = QComboBox()
        base = Path(__file__).parents[1]/'ml'/'comparison_weights'
        default_run = None
        try:
            default_run = json.loads((base/'manifest.json').read_text(encoding='utf-8'))['run']
        except (OSError,ValueError,KeyError):
            pass
        from ..ml.model_comparison import ModelComparison
        from ..ml.comparison_features import SCHEMA
        for path in sorted(base.glob('*/manifest.json'),reverse=True):
            try:
                if json.loads(path.read_text(encoding='utf-8')).get('feature_schema') != SCHEMA:
                    continue
            except (OSError,ValueError):
                continue
            self.profile_combo.addItem(ModelComparison._profile_label(path),str(path.resolve()))
            if path.parent.name == default_run:
                self.profile_combo.setCurrentIndex(self.profile_combo.count()-1)
        self.profile_combo.currentIndexChanged.connect(
            lambda _: self.comparison_profile_changed.emit(self.profile_combo.currentData()))
        layout.addWidget(self.profile_combo)
        intro = QLabel('Live model comparison — lock a target in the radar workspace.\n'
                       'Four of five model flags start a 5-second motion check. '
                       'Early reverse running rejects a candidate. Low motion, a stable centroid, or healthy-stream '
                       'target disappearance can support confirmation. Communication loss remains suspected.')
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.comparison_status = QLabel('Waiting for models')
        self.comparison_status.setWordWrap(True)
        layout.addWidget(self.comparison_status)
        self.comparison_table = QTableWidget(len(MODEL_NAMES), 5)
        self.comparison_table.setHorizontalHeaderLabels(['Model', 'Score', 'Threshold', 'Status', 'Last detection'])
        self.comparison_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.comparison_table.verticalHeader().hide()
        self.comparison_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.comparison_table.horizontalHeader().setSectionResizeMode(3,QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.comparison_table)
        note = QLabel('Event timeline — detections within 8 seconds are grouped for comparison, not verified as one physical fall.\n'
                      'Times are window-end timestamps; “—” means no flag from that model. Scores are not calibrated confidence.')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.event_table = QTableWidget(0, 5+len(MODEL_NAMES))
        self.event_table.setHorizontalHeaderLabels(['Event / profile', 'Target', 'First flag', *MODEL_NAMES.values(),
                                                   'Validation', 'Reason'])
        self.event_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.event_table.verticalHeader().hide()
        self.event_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.event_table)
        export = QPushButton('Export detection timeline (CSV)')
        export.clicked.connect(self._export_comparison)
        layout.addWidget(export)
        self.btn_acknowledge = QPushButton('Acknowledge suspected-fall warnings')
        self.btn_acknowledge.clicked.connect(lambda checked=False: self.validation_warnings_acknowledged.emit())
        self.btn_acknowledge.setEnabled(False)
        layout.addWidget(self.btn_acknowledge)
        self.tabs.addTab(page,'Compare models')

    def update_comparison(self, snapshot):
        if snapshot['revision'] == self._comparison_revision:
            return
        self._comparison_revision = snapshot['revision']
        warnings = snapshot.get('ensemble',{}).get('warnings',[])
        self.btn_acknowledge.setEnabled(bool(warnings))
        validation = snapshot.get('ensemble', {}).get('validation', {})
        validation_text = ''
        if validation:
            validation_text = f"\nPost-fall: {validation['state']} — {validation.get('reason','')}"
            if validation.get('confirmation_basis'):
                validation_text+=f" [basis: {validation['confirmation_basis']}]"
            if validation['state'] == 'validating':
                validation_text += (f" ({validation.get('elapsed_s',0):.1f}/{validation.get('observation_seconds',5):.1f}s; "
                                    f"low motion {validation.get('still_seconds',0):.1f}s)")
        warning_text = ('\nUnresolved suspected falls: '+', '.join(f"#{w['event_id']} ({w['target']})" for w in warnings[-5:])) if warnings else ''
        if len(warnings)>5:
            warning_text += f' — {len(warnings)} total; see the event timeline'
        self.comparison_status.setText(f"{snapshot.get('profile','')}\n{snapshot['message']}{validation_text}{warning_text}")
        keys = list(MODEL_NAMES)
        for i,key in enumerate(keys):
            row = snapshot['rows'][key]
            values = [row['name'], f"{row['score']:.3f}" if row['score'] is not None else '—',
                      f"{row['threshold']:.3f}" if row['threshold'] is not None else '—',
                      row['status'], time_label(row['last_detection'])]
            for j,value in enumerate(values):
                item = QTableWidgetItem(value)
                if row.get('error'):
                    item.setToolTip(row['error'])
                if row['status'] in ('Detected','Confirmed','Pre Alert','Above threshold'):
                    from PySide6.QtGui import QColor
                    item.setForeground(QColor('#FBBF24'))
                self.comparison_table.setItem(i,j,item)
        self._comparison_events = snapshot['events']
        signature = tuple((e['id'],e['timestamp'],e.get('validation',{}).get('state'),e.get('acknowledged_at'),
                           tuple((k,d['timestamp'],d['stage']) for k,d in e['detections'].items()))
                          for e in self._comparison_events)
        if signature == self._event_signature:
            return
        self._event_signature = signature
        events = list(reversed(self._comparison_events))
        self.event_table.setRowCount(len(events))
        for i,event in enumerate(events):
            profile_short = 'Sessions' if 'Within-person' in event.get('profile','') else 'Participants'
            values = [f"{event['id']} / {profile_short}", event['target'], time_label(event['timestamp'])]
            for key in keys:
                detection = event['detections'].get(key)
                values.append((f"{time_label(detection['timestamp'])}\n+{detection['timestamp']-event['timestamp']:.2f}s"
                               + (' confirmed' if detection['stage']=='confirmed' else '')) if detection else '—')
            validation = event.get('validation', {})
            outcome = validation.get('state','Not recorded')
            if event.get('acknowledged_at') is not None:
                outcome += ' (acknowledged)'
            values.extend([outcome,validation.get('reason','')])
            for j,value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(event.get('profile',''))
                self.event_table.setItem(i,j,item)
        self.event_table.resizeRowsToContents()

    def _export_comparison(self):
        path,_ = QFileDialog.getSaveFileName(self,'Export model detections','fall_model_detections.csv','CSV files (*.csv)')
        if not path:
            return
        try:
            with open(path,'w',newline='',encoding='utf-8') as handle:
                writer = csv.writer(handle)
                writer.writerow(['event','target','event_timestamp','model','detection_timestamp','delay_from_first_flag_s',
                                 'score','stage','confirmed_at','processed_at','profile','validation_state',
                                 'validation_reason','validation_started_at','validation_resolved_at',
                                 'observation_seconds','observed_seconds','still_seconds',
                                 'max_radial_speed_mms','max_planar_speed_mms','warning_kind','acknowledged_at',
                                 'reverse_displacement_mm','reverse_heading_cosine','reverse_fresh_coverage',
                                 'confirmation_basis','absence_seconds','stationary_seconds'])
                for event in self._comparison_events:
                    validation = event.get('validation', {})
                    for key,detection in event['detections'].items():
                        writer.writerow([event['id'],event['target'],event['timestamp'],key,detection['timestamp'],
                                         detection['timestamp']-event['timestamp'],detection['score'],detection['stage'],
                                         validation.get('confirmed_at') or '',detection['processed_at'],event.get('profile',''),
                                         validation.get('state','Not recorded'),validation.get('reason',''),
                                         validation.get('started_at',''),validation.get('resolved_at') or '',
                                         validation.get('observation_seconds',''),validation.get('observed_seconds',''),
                                         validation.get('still_seconds',''),validation.get('max_radial_speed_mms',''),
                                         validation.get('max_planar_speed_mms',''),validation.get('warning_kind',''),
                                         event.get('acknowledged_at') or '',
                                         validation.get('reversal',{}).get('displacement_mm',''),
                                         validation.get('reversal',{}).get('heading_cosine',''),
                                         validation.get('reversal',{}).get('coverage',''),validation.get('confirmation_basis',''),
                                         validation.get('absence_seconds',''),validation.get('stationary_seconds','')])
        except OSError as exc:
            QMessageBox.warning(self,'Export failed',str(exc))

    def _set_state_style(self, stage: str, votes: int = 0):
        """Update the state label appearance based on alert stage."""
        if stage == "confirmed" and votes >= 4:
            self.lbl_state.setText(f"🚨 FALL CONFIRMED ({votes}/5 MODELS) 🚨")
            self.lbl_state.setStyleSheet(
                "color: white; background-color: #DC2626; border-radius: 10px; padding: 10px;"
                "border: 3px solid #FCA5A5;"
            )
        elif stage == 'pre_alert':
            self.lbl_state.setText(f'CHECKING POST-FALL MOTION ({votes}/5 MODELS)')
            self.lbl_state.setStyleSheet('color: #1E293B; background-color: #F59E0B; border-radius: 10px; padding: 10px;')
        elif stage == 'suspected':
            self.lbl_state.setText(f'SUSPECTED FALL — REVIEW REQUIRED ({votes}/5 MODEL FLAGS)')
            self.lbl_state.setStyleSheet('color: #1E293B; background-color: #F59E0B; border-radius: 10px; padding: 10px;')
        elif stage in ('rejected','unverified'):
            self.lbl_state.setText(f'CANDIDATE {stage.upper()} ({votes}/5 MODEL FLAGS — NO CONFIRMED ALERT)')
            self.lbl_state.setStyleSheet('color: #F8FAFC; background-color: #475569; border-radius: 10px; padding: 10px;')
        elif votes > 0 and votes < 4:
            self.lbl_state.setText(f"VOTING: {votes}/5 MODELS (NEED 4/5 — NO ALERT)")
            self.lbl_state.setStyleSheet(
                "color: #1E293B; background-color: #F59E0B; border-radius: 10px; padding: 10px;"
                "border: 3px solid #FCD34D;"
            )
        else:
            self.lbl_state.setText("NORMAL (5-MODEL ENSEMBLE ARMED)")
            self.lbl_state.setStyleSheet(
                "color: #10B981; background-color: #064E3B; border-radius: 10px; padding: 10px;"
            )

    def _toggle_sound(self):
        self._sound_enabled = not self._sound_enabled
        if self._sound_enabled:
            self.btn_sound.setText("🔔 Sound: ON")
        else:
            self.btn_sound.setText("🔕 Sound: OFF")

    def reset_count(self):
        self.fall_count = 0
        self.lbl_count_val.setText("0")
        self.cooldown_frames = 0

    def update_alert_history(self, history: list[dict]):
        """Update the alert history log from PostFallValidator's history."""
        if not history:
            return
        
        lines = []
        for event in reversed(history[-10:]):  # Show last 10 events
            time_str = event.get("time", "??:??:??")
            event_type = event.get("type", "UNKNOWN")
            prob = event.get("probability", 0)
            reason = event.get("reason", "")
            
            if event_type == "CONFIRMED":
                prefix = "🔴"
            else:
                prefix = "🟡"
            
            lines.append(f"{prefix} [{time_str}] {event_type} (p={prob:.2f}) - {reason}")
        
        self.txt_history.setPlainText("\n".join(lines))

    @Slot(bool, float, str)
    def update_fall_status(self, is_falling: bool, probability: float, stage: str = "normal", votes: int = 0):
        """Updates the monitor with the latest prediction and alert stage."""
        # Decrease cooldown
        if self.cooldown_frames > 0:
            self.cooldown_frames -= 1
            
        prob_pct = int(probability * 100)
        self.bar_prob.setValue(prob_pct)
        
        # Color the probability bar based on severity
        if prob_pct > 75:
            self.bar_prob.setStyleSheet("""
                QProgressBar { border: 2px solid #334155; border-radius: 5px; text-align: center; color: white; font-weight: bold; }
                QProgressBar::chunk { background-color: #EF4444; }
            """)
        elif prob_pct > 30:
            self.bar_prob.setStyleSheet("""
                QProgressBar { border: 2px solid #334155; border-radius: 5px; text-align: center; color: white; font-weight: bold; }
                QProgressBar::chunk { background-color: #F59E0B; }
            """)
        else:
            self.bar_prob.setStyleSheet("""
                QProgressBar { border: 2px solid #334155; border-radius: 5px; text-align: center; color: white; font-weight: bold; }
                QProgressBar::chunk { background-color: #10B981; }
            """)

        # Update state display based on alert stage
        stage_key = (stage, votes >= 4, votes)
        if stage_key != self._current_stage_key:
            self._set_state_style(stage, votes)
            self._current_stage_key = stage_key
            self._current_stage = stage

        # Track confirmed falls
        if stage == "confirmed" and votes >= 4:
            if not self.is_falling and self.cooldown_frames == 0:
                self.fall_count += 1
                self.lbl_count_val.setText(str(self.fall_count))
                self.cooldown_frames = 100  # ~5 seconds at 20fps before counting another
            self.is_falling = True
        else:
            self.is_falling = False
