# riaps:keep_import:begin
from riaps.run.comp import Component
import spdlog
from xlrd import open_workbook, xldate_as_tuple
from dateutil.relativedelta import relativedelta
from datetime import datetime, timedelta
import threading
import zmq
import time
import yaml
from queue import Queue
import re

# riaps:keep_import:end

class BuildingInterfaceThread(threading.Thread):
    ''' 
    This class implements a reusable interface for the Chargepoint either using the SOAP API service or a sql database. The configuration is specified in a yaml file.
    It can receive two types of messages from an associated manager:
    Query - A list of quantity names as strings - {'TotalPower', 'Temp', 'HVAC', 'Lighting', 'all'}
    Ans - list of dictionaries corresponding to the query
    Command - tbd
    Ans - tbd
    '''

    def __init__(self,configfile,relay,logger):
        '''Constructor method
        '''
        threading.Thread.__init__(self)
        self.relay = relay
        self.logger = logger
        self.context = zmq.Context()
        self.terminated = threading.Event()
        self.fmt = '%Y-%m-%d %H:%M:%S'
        self.plug = None
        _config = "config/" + configfile
        with open(_config, 'r') as stream:
            try:
                auth_config= yaml.safe_load(stream)
            except yaml.YAMLError as exc:
                self.logger.error(exc)
        self.mode = auth_config['mode']
        if self.mode == 'realtime':
            pass
        elif self.mode == 'playback':
            self.filename = auth_config['filename']
            self.item_sheet_map = auth_config['item_sheet_map']
            self.sheet_format = auth_config['sheet_format']
            try:
                self.tStart = auth_config['tStart']
            except:
                self.tStart = None
            try:
                self.Ts = auth_config['Ts']
            except:
                self.Ts = 60
            self.book = open_workbook('config/'+self.filename)
            self.last_search = {}

    def run(self):
        '''
        polls on a zmq ssocket for incoming messages from inner thread
        '''
        self.logger.info("starting device inner thread")
        self.plug = self.relay.setupPlug(self)    # Ask RIAPS port to make a plug (zmq socket) for this end
        self.poller = zmq.Poller()                  # Set up poller to wait for messages from either side
        self.poller.register(self.plug, zmq.POLLIN) # plug socket (connects to trigger port of parent device comp)
        while 1:
            if self.terminated.is_set(): break
            socks = dict(self.poller.poll(1000.0))  # Run the poller: wait input from either side, timeout if none
            if len(socks) == 0:
                pass
#                 self.logger.info('DeviceThread timeout')
            if self.terminated.is_set(): break                           # Send it to the plug
            if self.plug in socks and socks[self.plug] == zmq.POLLIN:   # Input from the plug
                message = self.plug.recv_pyobj()
                msgtype = message[0]
                if msgtype == 'qry':
                    qty = message[1]
                    resp = self.handleQry(qty) 
                    self.plug.send_pyobj(resp)                        # Send it to the console
        self.logger.info('DeviceThread ended')
        
    def terminate(self):
        '''
        terminate the thread
        '''
        self.terminated.set()
        if self.mode == 'playback':
            try: self.cursor.close()
            except: pass
        self.logger.info('DeviceThread terminating')
        
    
     
    def getRealtimeData(self, qty):
        '''Get charging session information in real time mode from SOAP API 
        :param qty: list of quantities requested
        :type qty: list
        :return: the session data as a list of dictionaries
        :rtype: list
        '''
        resultlist = []
        return resultlist
                    
            
    def handleQry(self, qty):
        '''handle query request from manager
        :param qty: list of quantities requested
        :type qty: list
        :return: the session data as a list of dictionaries
        :rtype: list
        '''
        if self.mode == 'playback':
            results = self.getPlaybackData(qty)
        elif self.mode == 'realtime':
            results = self.getRealtimeData(qty)
        return ['qry',results]
    
    def getPlaybackData(self, qty):
        ''' play data from an excel spreadsheet and return the results
        :param qty: list of quantities requested
        :type qty: list
        :return: the session data as a list of dictionaries
        :rtype: list
        '''
        resultlist = []
        results = {}
        patrn = re.compile(r'[^\d.]+')
        
        
        if self.tStart is None:
            self.tStart = datetime.now()-relativedelta(years=1)
            self.tStart = self.tStart.replace(minute = 0, second = 0, microsecond = 0)
            self.tStart = datetime.strftime(self.tStart, '%Y-%m-%d %H:%M:%S')
            self.logger.info(self.tStart)
        tStart_dt = datetime.strptime(self.tStart, self.fmt)
        for item in qty:
#             find the appropriate sheets based on the mapping
            sheetlist = []
            #                 initialize search history tfor each quuuery item
            if item not in self.last_search:
                self.last_search[item] = {}
            for key, sheetnames in self.item_sheet_map.items():
                for sheetname in sheetnames:
                    if key == item or item == 'all':
                        if sheetname not in sheetlist:
                            sheetlist.append(sheetname)
#             open each sheet and get data
            for sheetname in sheetlist:
                sheet = self.book.sheet_by_name(sheetname)
#                 initialize the specific sheet row search history index
                if sheetname not in self.last_search[item]:
                    self.last_search[item][sheetname] = 0
#                 find the column names and its associated date column based on the item
                col_date_map = {}
                for cols in self.sheet_format[sheetname]:
                    coldetails = cols.split('_')
                    if item in coldetails[-1] or (item == 'all' and 'Date' not in coldetails[-1]):
                        col_date_map[cols] = cols.replace(patrn.search(coldetails[-1]).group(0), 'Date')
                        if col_date_map[cols] not in self.sheet_format[sheetname]:
                            col_date_map[cols] = 'Date'
#                 go through each row and fetch the values from the relevant columns
                candt = sheet.nrows 
                for row_idx in range(self.last_search[item][sheetname],sheet.nrows):
            
                    for data_col, date_col in  col_date_map.items():
#                         match the time stamp with the current time step
                        dt = sheet.cell_value(row_idx,int(self.sheet_format[sheetname][date_col]))
                        try: 
                            dt = xldate_as_tuple(dt, self.book.datemode)
                            dt = datetime(*dt)
                            dt = dt.replace(minute = 0, second = 0, microsecond = 0)
                        except:
                            pass
                        else:
                            if dt == tStart_dt:
                                results['Date'] = self.tStart
                                results[data_col] = sheet.cell_value(row_idx,int(self.sheet_format[sheetname][data_col]))
                                if row_idx < candt:
                                    candt = row_idx
                                self.last_search[item][sheetname] = candt
        if not results:
            results['Date'] = self.tStart
            results['HT_TotalPower'] = 0
            results['OutsideAirTemp'] = 72
        resultlist.append(results)
        self.tStart = datetime.strftime(tStart_dt + timedelta(minutes = self.Ts),self.fmt)
        return resultlist
    
    def get_plug(self):
        return self.plug


class BuildingInterface(Component):

# riaps:keep_constr:begin
    def __init__(self,configfile):
        super(BuildingInterface, self).__init__()
        self.DeviceThread = None
        self.identity = Queue()
        self.configfile = configfile
        self.logger.info("starting interface device")
# riaps:keep_constr:end

# riaps:handle_act:begin
    def handleActivate(self):
        self.DeviceThread = BuildingInterfaceThread(self.configfile,self.relay,self.logger) # Inside port, external zmq port
        self.DeviceThread.start() # Start thread
        plug = None
        while plug is None:
            plug = self.DeviceThread.get_plug()
            time.sleep(0.1)
        self.plugID = self.relay.get_plug_identity(plug)
        self.relay.activate()
# riaps:handle_act:end

# riaps:keep_command:begin
    def on_command(self):
        msg = self.command.recv_pyobj()
        self.identity.put(self.command.get_identity())
        self.logger.info("received: %s" % str(msg))
        self.relay.set_identity(self.plugID)
        self.relay.send_pyobj(['cmd',msg])
# riaps:keep_command:end

# riaps:keep_request:begin
    def on_request(self):
        msg = self.request.recv_pyobj()
        self.identity.put(self.request.get_identity())
        self.logger.info("received: %s" % str(msg))
        self.relay.set_identity(self.plugID)
        self.relay.send_pyobj(['qry',msg])
# riaps:keep_request:end

# riaps:keep_relay:begin
    def on_relay(self):
        recv = self.relay.recv_pyobj()
        self.logger.info("received response: %s" % str(recv))
        msgtype, ans = recv
        if msgtype == 'qry':
            self.request.set_identity(self.identity.get())
            self.request.send_pyobj(ans)
        elif msgtype == 'cmd':
            self.command.set_identity(self.identity.get())
            self.command.send_pyobj(ans)
# riaps:keep_relay:end

# riaps:keep_impl:begin

    def __destroy__(self):
       self.logger.info("exiting")
       self.DeviceThread.terminate()
       self.DeviceThread.join()

# riaps:keep_impl:end