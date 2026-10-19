"""Render real Tk widgets with explicitly simulated Qubes/Bridge/Tunnel states.

No Qrexec, tunnel or pairing operation is executed. All displayed values are
examples. Native Qubes operation must still be tested on Qubes OS.
Run under Xvfb; optional first argument selects the artifact directory.
"""
import gc
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock
import tkinter as tk
from PIL import ImageGrab

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import admin_in_the_loop as a


def main():
    output = Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).resolve().parents[1]/'doc/assets/connection-ux'
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='aitl-connection-render-') as directory:
        core = a.AppCore(connection_store=a.ConnectionStore(Path(directory)/'config'))
        root = tk.Tk()
        ui = a.ReviewUI(root, core)
        errors = []
        root.report_callback_exception = lambda *_: errors.append('tk callback')
        with mock.patch.object(a, 'qubes_detected', return_value=True), \
                mock.patch.object(a, 'source_qube_name', return_value='personal'), \
                mock.patch.object(core, 'begin_tunnel_probe'), \
                mock.patch.object(core, 'hello_bridge') as hello, \
                mock.patch.object(core, 'begin_pair_remote') as pair:
            dialog = ui.connection_settings()
            dialog.window.geometry('860x780+0+0')
            def capture(name):
                dialog.canvas.yview_moveto(0)
                for _ in range(4):
                    root.update()
                    time.sleep(.015)
                window = dialog.window
                x,y = window.winfo_rootx(), window.winfo_rooty()
                ImageGrab.grab(bbox=(x,y,x+window.winfo_width(),y+window.winfo_height()),
                               xdisplay=os.environ['DISPLAY']).save(output/(name+'.png'))
                assert not errors, errors
            try:
                capture('00-standort')
                dialog.location.set('QREXEC')
                dialog.fields['qrexec_target'].set('ai-bridge')
                capture('01-ziel-qube')
                dialog.wizard_next()
                capture('02-bridge-starten')
                # Explicit failure fixture: show useful policy help without invoking Qrexec.
                result = {'phase':'qrexec_target_unreachable','reachable':False,'observed_pin':None}
                with mock.patch.object(core, 'verify_qrexec_connection', return_value=result):
                    dialog.verify_qrexec()
                capture('02b-verbindung-pruefen')
                dialog.qrexec_help.grid_remove()
                dialog.qrexec_help_visible = False
                dialog.qrexec_verified = True
                dialog.qrexec_observed_pin = '0123456789abcdef'*4
                dialog.show_qrexec_pin()
                dialog.qrexec_status.set('Beispiel: Code wurde im Ziel-Terminal angefordert. Fingerprint dort vollständig vergleichen.')
                dialog.fields['qrexec_code'].set('ABCD-EFGH')
                dialog.wizard_goto(2)
                capture('03-koppeln')
                # Synthetic authenticated state: no actual credentials or API requests.
                profile = a.ConnectionProfile('https://127.0.0.1:8443', '0123456789abcdef'*4,
                    'b'*32, 'c'*32, 'd'*64)
                core.bridge_profile, core.bridge_state, core.bridge_instance = profile, 'CONNECTED', 'e'*32
                core.remote_tunnel = {'phase':'missing'}
                dialog.fields['qrexec_tunnel_id'].set('tunnel_'+'0123456789abcdef'*2)
                dialog.fields['qrexec_runtime_key'].set('BEISPIEL-KEIN-ECHTER-API-KEY')
                dialog.render()
                capture('04-secure-tunnel')
                core.remote_tunnel = {'phase':'installing', 'step':'verify'}
                dialog.render()
                capture('04b-tunnel-fortschritt')
                core.remote_tunnel = {'phase':'connected'}
                core.chat_binding = {'code':'ABCDEFGH', 'generation':1, 'status':'ACTIVE',
                    'server_time':100, 'expires_at':86500, 'retry_at':None, 'restriction_scope':None}
                core.chat_binding_received_at = time.monotonic()
                dialog.render()
                capture('05-chat-binden')
                # Saved restart example: only the recovery error/state is injected.
                core.disconnect_bridge()
                core.connection_store.save_connection(profile, None, {'target':'ai-bridge','port':8443})
                core.saved_connection = core.connection_store.load_connection()
                core.recovery_state, core.recovery_error = 'NEEDS_ATTENTION', 'qrexec_target_unreachable'
                dialog.window.destroy()
                dialog = ui.connection_settings()
                dialog.window.geometry('860x780+0+0')
                capture('06-wiederherstellen')
                dialog.open_recovery_setup()
                dialog.window.geometry('640x480+0+0')
                capture('07-kleines-fenster')
                hello.assert_not_called()
                pair.assert_not_called()
                assert core.review is None
                assert core.bridge_worker is None
                print('Rendered 10 real Tk views with explicitly simulated Qubes/provider states; no external operations.')
            finally:
                core.close()
                for callback in root.tk.call('after','info'):
                    root.after_cancel(callback)
                root.destroy()
                ui = dialog = root = core = None
                gc.collect()

if __name__ == '__main__':
    main()
