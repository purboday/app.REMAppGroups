'''
Logger component

- log msg format: (tag, measurement, [ time ], [ values ]) 
'''
from riaps.run.comp import Component
from influxdb import InfluxDBClient
from influxdb.client import InfluxDBClientError
import json
import logging
from datetime import datetime
import os
import yaml

BATCH_SIZE = 60

class Logger(Component):
    def __init__(self, configfile):
        super().__init__()
        _config = "config/" + configfile
        with open(_config, 'r') as stream:
            try:
                db_config= yaml.safe_load(stream)
            except yaml.YAMLError as exc:
                print(exc)
        self.db_name = db_config['db_name']
        self.db_drop = db_config['db_drop']
        self.point_values = []
        try:
            self.client = InfluxDBClient(host=db_config['db_host'], port=db_config['db_port'],
                                         database=db_config['db_name'], username=db_config['db_user'], password=db_config['db_password'])
            self.client.create_database(db_config['db_name'])
            self.client.switch_database(db_config['db_name'])
        except:
            self.logger.error('database connection failed')
            self.client = None


    def on_logData(self):
        datastream = self.logData.recv_pyobj()
        for point in datastream:
            tag, measurement, times, values = point
            assert len(times) == len(values)
            if self.client == None: return
            for i in range(len(times)):
                self.point_values.append({
                        "time" : datetime.fromtimestamp(times[i]).isoformat()+'Z',
                        "tags" : tag,
                        "measurement" : measurement,
                        "fields" : values[i]
                    })
            # if len(self.point_values) >= BATCH_SIZE:
#             self.logger.info(str(self.point_values))
            self.client.write_points(self.point_values)
            self.point_values = []

    def __destroy__(self):
        if self.client and self.db_drop:
            self.client.drop_database(self.db_name)
            
            