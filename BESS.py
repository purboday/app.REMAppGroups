'''
RIAPS dispatch example
Battery Storage component
'''

from riaps.run.comp import Component
import os
import time
import random
from array import array
from riaps.run.exc import PortError
from queue import Queue
from builtins import getattr
import numpy as np
from datetime import datetime, timedelta

class BESS(Component):
    '''
    A model of a Battery Energy Storage System, it sends out its state of charge and receives power from the aggregator 
    '''
    def __init__(self,Rbess,Cbattery,SoCl,SoCu,SoC0,SoCend,tStart='',Ts=60):
        super(BESS, self).__init__()
        self.fmt = '%Y-%m-%d %H:%M:%S'
        self.Rbess,self.Cbattery,self.SoCl,self.SoCu,self.SoC,self.SoCend  = Rbess,Cbattery,SoCl,SoCu,SoC0,SoCend
        if tStart == '':
            self.currTime = datetime.strftime(datetime.now(),self.fmt)
        else:
            self.currTime = tStart
        self.Ts = Ts
        self.step = 0
        self.IDqueue = Queue()

# riaps:keep_request:begin
    def on_request(self):
        msg = self.request.recv_pyobj()
        self.IDqueue.put(self.request.get_identity())
        self.logger.info("received request: %s" % str(msg))
        qryMap = {}
        for item in msg:
            try : qryMap[item] = getattr(self,item)
            except:
                self.logger.error("attribute %s not found" % item)
                qryMap[item] = 'NA'
        self.updateTime()
        self.request.set_identity(self.IDqueue.get())
        self.request.send_pyobj({'Date': self.currTime, 'attr': qryMap})
            
# riaps:keep_request:end

    def on_command(self):
        msg = self.command.recv_pyobj()
        self.IDqueue.put(self.request.get_identity())
        self.logger.info("received: %s" % str(msg))
        cmd, value = msg
        if cmd == 'updateSoC':
            self.updateSoC(value)
        ans = 'ok'
        self.command.set_identity(self.IDqueue.get())
        self.command.send_pyobj(ans)

# riaps:keep_command:end

    def updateTime(self):
        self.currTime = datetime.strftime(datetime.strptime(self.currTime,self.fmt)+timedelta(minutes=self.Ts), self.fmt)

    
    def updateSoC(self, Pbattery):
        self.SoC += Pbattery/self.Cbattery
        self.logger.info("new SoC: %f" % self.SoC)
        
    def __destroy__(self):
        self.logger.info("exiting")