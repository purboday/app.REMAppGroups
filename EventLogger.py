'''
Event Logger component

- log msg format: [{header: value}]
'''
from riaps.run.comp import Component
import spdlog
import capnp
import remapp_capnp
from datetime import datetime
import csv
import yaml
import os

class EventLogger(Component):
    def __init__(self, configfile):
        super().__init__()
        _config = "config/" + configfile
        with open(_config, 'r') as stream:
            try:
                self.csv_config= yaml.safe_load(stream)
            except yaml.YAMLError as exc:
                print(exc)
        self.eventList = []
                
    def handleActivate(self):        
        filename = os.path.join(self.csv_config['location'], self.csv_config['filename'])
        try:
            with open(filename, 'w', newline='') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=self.csv_config['headers'])
                writer.writeheader()
        except PermissionError as e:
            self.logger.error('Permission denied: unable to open file %s' % (filename))
            
    def on_EventLog(self):
        eventData = self.EventLog.recv_pyobj()
        self.logger.info('received event log data')
        assert list(eventData.keys()) == self.csv_config['headers'], 'received message headers donot match the csv file'
        self.eventList.append(eventData)
        
    def on_update(self):
        now = self.update.recv_pyobj()
        try:
            with open(filename, 'a', newline='') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=self.csv_config['headers'])
                writer.writerows(self.eventList)
        except PermissionError as e:
            self.logger.error('Permission denied: unable to open file %s' % (filename))
        else:
            self.logger.info('written %d records to file' % (len(self.eventList)))
            self.eventList = []