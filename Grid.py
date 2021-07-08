# import riaps
from riaps.run.comp import Component
import logging
import random
import os
import threading
import zmq
import time
import math
import configparser
from pathlib import PurePath
import netifaces

class GridThread(threading.Thread):
    '''
    Inner Grid thread
    '''
    def __init__(self,trigger,endpoint,logger):
        threading.Thread.__init__(self)
        self.logger = logger
        self.active = threading.Event()
        self.active.clear()
        self.waiting = threading.Event()
        self.terminated = threading.Event()
        self.terminated.clear()
        self.trigger = trigger              # inside RIAPS port
        self.endpoint = endpoint                    # port number for socket to connect to connect to console client 
        self.context = zmq.Context()
        self.cons = self.context.socket(zmq.SUB)    # Create zmq REP socket
        
#         conf = configparser.ConfigParser()
#         conf.read(PurePath(os.environ['RIAPSHOME'],'etc','riaps.conf'))
#         ip = netifaces.ifaddresses(conf.get('RIAPS','nic_name'))[netifaces.AF_INET][0]['addr']
#         self.cons.bind("tcp://10.0.0.215:9876")
        self.cons.bind("tcp://"+endpoint)
        self.cons.subscribe("")
        self.logger.info('GridThread _init()_ed')
    
    def run(self):
        self.logger.info('GridThread starting')
        self.plug = self.trigger.setupPlug(self)    # Ask RIAPS port to make a plug (zmq socket) for this end
        self.poller = zmq.Poller()                  # Set up poller to wait for messages from either side
        self.poller.register(self.cons, zmq.POLLIN) # console socket (connects to console client)
        self.poller.register(self.plug, zmq.POLLIN) # plug socket (connects to trigger port of parent device comp)
        while 1:
            self.active.wait(None)                  # Events to handle activation/termination
            if self.terminated.is_set(): break
            if self.active.is_set():                # If we are active
                socks = dict(self.poller.poll(1000.0))  # Run the poller: wait input from either side, timeout if none
                if len(socks) == 0:
#                     self.logger.info('GridThread timeout')
                    pass
                if self.terminated.is_set(): break
                if self.cons in socks and socks[self.cons] == zmq.POLLIN:   # Input from the console
#                     self.logger.info('GOT SOMETHING INSIDE THREAD')
                    message = self.cons.recv_pyobj()
                    self.plug.send_pyobj(message)                           # Send it to the plug
                if self.plug in socks and socks[self.plug] == zmq.POLLIN:   # Input from the plug
                    message = self.plug.recv_pyobj()
#                     self.cons.send_pyobj(message)                           # Send it to the console
        self.logger.info('GridThread ended')
               

    def activate(self):
        self.active.set()
        self.logger.info('GridThread activated')
                    
    def deactivate(self):
        self.active.clear()
        self.logger.info('GridThread deactivated')
    
    def terminate(self):
        self.active.set()
        self.terminated.set()
        self.logger.info('GridThread terminating')

class Grid(Component):
    def __init__(self,endpoint):
        super(Grid, self).__init__()
        self.logger.info("Grid - starting")
        self.endpoint = endpoint
        self.GridThread = None  # Cannot manipulate ports in constructor or start threads, use clock pulse
        self.microgridMode = 0
        self.gridPowerMode = 0
        self.gridPower = 1000
        self.weightBuilding = 1
        self.weightEv = 1


    def on_clock(self):
        if self.GridThread == None: # First clock pulse
            self.GridThread = GridThread(self.trigger,self.endpoint,self.logger) # Inside port, external zmq port
            self.GridThread.start() # Start thread
            time.sleep(0.1)
            self.trigger.activate()
        now = self.clock.recv_pyobj()   # Receive time (as float)
        self.clock.halt()               # Halt this timer (don't need it anymore)

    def __destroy__(self):
        self.logger.info("__destroy__")
        self.GridThread.deactivate()
        self.GridThread.terminate()
        self.GridThread.join()
        self.logger.info("__destroy__ed")
        
    def on_trigger(self):                       # Internally triggered operation (
        key,val = self.trigger.recv_pyobj()         # Receive message from internal thread
        self.logger.info('FROM GUI: %s' % str((key,val)))
        if key == 'MODE':
            if val == 'ISLAND':
                self.microgridMode = 1
            elif val == 'PURCHASED':
                self.microgridMode = 0
                self.gridPowerMode = 0
            else:
                self.microgridMode = 0
                self.gridPowerMode = 1
        elif key == 'GRID':
            self.gridPower = val
        elif key == 'WEIGHT':
            self.weightEv = val['CHARGER']
            self.weightBuilding = val['BUILDING']      
    
    def on_ticker(self):
        msg = self.ticker.recv_pyobj()
        self.setPoint.send_pyobj((msg, {'microgridMode':self.microgridMode,
                                     'gridPowerMode':self.gridPowerMode,
                                     'gridPower':self.gridPower,
                                     'weightBuilding':self.weightBuilding,
                                     'weightEv':self.weightEv}))
