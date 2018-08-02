'''
Server based on tornado to receive commands from a html page (websockets) and control 
the outputs of a raspberry pi.

- to be used with RCHummer_Gamepad.html (https://github.com/ricardodeazambuja/HTML-Gamepad)
'''

import time

import json

import os

import tornado.httpserver
import tornado.websocket
import tornado.ioloop
import tornado.web

import tornado.gen
import datetime

import math

MIN_FREQUENCY_MOTOR_LOOP = 50 #in Hertz
PWM_FREQUENCY = 100 #in Hertz

PINS_USED = [[22,27], [23,24]] #[[pins LR],[pins FB]]
# More details https://www.raspberrypi.org/documentation/usage/gpio/README.md

try:
    import pigpio
    raspberrypi = True
    pi = None

except ImportError:
    print("pigpio is not available...", flush=True)
    raspberrypi = False

websocket_state = False

shutdown_pi = False

motor_cmds = [[],[]]

time_vec = [None,None]

tc = 5.0

def actuate_motor(motor_id):
    if motor_cmds[motor_id]:
        if time_vec[motor_id]:
            if time_vec[motor_id] < motor_cmds[motor_id]['timestamp']:
                new_dutycycle = int(255*(1-math.exp(-abs(motor_cmds[motor_id]['cmd']/tc)))) # new asymptotic curve
                if 100 >= motor_cmds[motor_id]['cmd'] > 0:
                    pi.set_PWM_dutycycle(PINS_USED[motor_id][0], 0)
                    # pi.set_PWM_dutycycle(PINS_USED[motor_id][1], int(255*abs(motor_cmds[motor_id]['cmd']/100.0)))
                    pi.set_PWM_dutycycle(PINS_USED[motor_id][1], new_dutycycle if new_dutycycle<=253 else 255) # 253 to compensate
                elif -100 <= motor_cmds[motor_id]['cmd'] < 0:
                    pi.set_PWM_dutycycle(PINS_USED[motor_id][1], 0)
                    # pi.set_PWM_dutycycle(PINS_USED[motor_id][0], int(255*abs(motor_cmds[motor_id]['cmd']/100.0)))                    
                    pi.set_PWM_dutycycle(PINS_USED[motor_id][0], new_dutycycle if new_dutycycle<=253 else 255)
                else:
                    # everything stops dutycycle=0
                    pi.set_PWM_dutycycle(PINS_USED[motor_id][0], 0)
                    pi.set_PWM_dutycycle(PINS_USED[motor_id][1], 0)
                time_vec[motor_id] = motor_cmds[motor_id]['timestamp']
        else:
            time_vec[motor_id] = motor_cmds[motor_id]['timestamp'] #first command, just used to start time_vec

        # print("MOTOR_CMDS:", motor_cmds, flush=True)

@tornado.gen.coroutine
def motors_loop():
    while True:
        if raspberrypi and websocket_state:
            actuate_motor(0)
            actuate_motor(1)
        yield tornado.gen.Task(
            tornado.ioloop.IOLoop.current().add_timeout,
            datetime.timedelta(milliseconds=1000.0/MIN_FREQUENCY_MOTOR_LOOP))
# Another possible implementation would be to use tornado.ioloop.PeriodicCallback


class ControllerWS(tornado.websocket.WebSocketHandler):
    def open(self):
        global websocket_state, pi
        x_real_ip = self.request.headers.get("X-Real-IP")
        user_ip = x_real_ip or self.request.remote_ip
        user_agent = self.request.headers["User-Agent"]

        self.last_timestamp = None
        
        print('User IP:', user_ip, flush=True)
        print('User browser:',user_agent, flush=True)
        print("WebSocket opened", flush=True)

        if raspberrypi:
            pi = pigpio.pi() # Connect to local Pi, you could connect through network too.
                            # http://abyz.me.uk/rpi/pigpio/python.html#pigpio.pi

            if not pi.connected:
                print("There's something wrong with pigpio, is the daemon running???", flush=True)
                raise KeyboardInterrupt
            for pin in [i for j in PINS_USED for i in j]:
                pi.set_mode(pin, pigpio.OUTPUT)
                pi.set_PWM_frequency(pin, PWM_FREQUENCY) # http://abyz.me.uk/rpi/pigpio/python.html#set_PWM_frequency
                pi.set_PWM_dutycycle(pin, 0) # starts off; goes from 0 to 255
            websocket_state = True
            print("pigpio is ready to rock!", flush=True)


    def on_message(self, cmd):
        # x_real_ip = self.request.headers.get("X-Real-IP")
        # user_ip = x_real_ip or self.request.remote_ip
        # user_agent = self.request.headers["User-Agent"]
        
        cmd_converted = json.loads(cmd)

        if self.last_timestamp==None:
            self.last_timestamp = {'btn_LR':cmd_converted['timestamp'], 
                                   'btn_FB':cmd_converted['timestamp']}
            print('Initial timestamp:',self.last_timestamp, flush=True)
        else:
            if cmd_converted['id']=='btn_LR':
                motor_cmds[0]=cmd_converted
            elif cmd_converted['id']=='btn_FB':
                motor_cmds[1]=cmd_converted
            else:
                print("Wrong command!", flush=True)

            # print('User IP:', user_ip, flush=True)
            # print('User browser:',user_agent, flush=True)
            # print("CMD:", cmd_converted, flush=True)

    def on_close(self):
        global websocket_state
        if raspberrypi:
            for pin in [i for j in PINS_USED for i in j]:
                pi.write(pin, 0)
            pi.stop()      
        websocket_state = False
        print("WebSocket closed", flush=True)

#     def check_origin(self, origin):
#         return True    

class Controller(tornado.web.RequestHandler):
    def get(self):
        x_real_ip = self.request.headers.get("X-Real-IP")
        user_ip = x_real_ip or self.request.remote_ip
        user_agent = self.request.headers["User-Agent"]
        
        print('User IP:', user_ip, flush=True)
        print('User browser:',user_agent, flush=True)

        # The html file comes from this repo: https://github.com/ricardodeazambuja/HTML-Gamepad
        with open('/home/pi/RCHummer_Gamepad.html', 'r') as htmlfile:
            data=htmlfile.read()
        self.write(data)
        
class ShutdownPi(tornado.web.RequestHandler):
    def get(self):
        global shutdown_pi

        x_real_ip = self.request.headers.get("X-Real-IP")
        user_ip = x_real_ip or self.request.remote_ip
        user_agent = self.request.headers["User-Agent"]

        self.write("<!doctype html>")
        self.write("<html><head><title>Shutdown Pi</title></head><body>")
        self.write("<h1>This raspberry pi is shutting down</h1>")
        self.write("<h2>"+user_ip+"</h2>")
        self.write("<h2>"+user_agent+"</h2>")
        self.write("</body></html>")

        shutdown_pi = True

        tornado.ioloop.IOLoop.current().call_later(5, tornado.ioloop.IOLoop.instance().stop)

handlers = [(r'/ws', ControllerWS),
            (r'/controller', Controller),
            (r'/shutdown', ShutdownPi),
            (r'/', Controller),
            (r'/(.*)', tornado.web.StaticFileHandler, {'path': os.getcwd()})
            ]

application = tornado.web.Application(handlers, websocket_ping_interval=5, websocket_ping_timeout=15})
# Every [websocket_ping_interval] seconds, tornado will ping the client. If the client doesn't answer (pong)
# after [websocket_ping_timeout] seconds, the websocket connection will be closed.
# See http://www.tornadoweb.org/en/stable/web.html#application-configuration for more details.

if __name__ == "__main__":
    http_server = tornado.httpserver.HTTPServer(application)
    http_server.listen(8080)
    motors_loop()
    # https://stackoverflow.com/a/17105220
    try:
        tornado.ioloop.IOLoop.instance().start()
    except:
        tornado.ioloop.IOLoop.instance().stop()
    finally:
        # disable the motors, etc
        if raspberrypi and websocket_state:
            for pin in [i for j in PINS_USED for i in j]:
                pi.write(pin, 0)
            pi.stop()
        print('tornado exiting...', flush=True)

        if shutdown_pi:
            print('User called shutdown...', flush=True)
            os.system("sudo shutdown -h now") 