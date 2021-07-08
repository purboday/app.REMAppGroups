# riaps:keep_import:begin
from riaps.run.comp import Component
import spdlog
from zeep import Client
import zeep.helpers
from zeep.wsse.username import UsernameToken
import sqlite3
from datetime import datetime, timedelta
import threading
import zmq
import time
import yaml
from queue import Queue
from dateutil.relativedelta import relativedelta
import pandas as pd

# riaps:keep_import:end

class ChargerInterfaceThread(threading.Thread):
    ''' 
    This class implements a reusable interface for the Chargepoint either using the SOAP API service or a sql database. The configuration is specified in a yaml file.
    It can receive two types of messages from an associated manager:
    Query - A list of quantity names as strings - {'energyConsumed', 'rollingPowerAvg', 'peakPower', 'all'} 
    Ans - list of dictionaries {{'stationID', 'portNumber', 'sessionID', 'stationTime', quantity: value pairs}
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
                print(exc)
        self.mode = auth_config['mode']
        if self.mode == 'realtime':
            self.username = auth_config['username']
            self.password = auth_config['password']
            self.wsdl_url = auth_config['wsdl_url']
            self.client = Client(self.wsdl_url, wsse=UsernameToken(self.username, self.password))
        elif self.mode == 'playback':
            self.dbname = auth_config['dbname']
            try:
                self.tStart = auth_config['tStart']
            except:
                self.tStart = None
            try:
                self.Ts = auth_config['Ts']
            except:
                self.Ts = 15
            self.conn = None
            self.cursor = None
        elif self.mode == 'playbackCSV':
            self.sourcefile = pd.read_csv('config/'+auth_config['filename'], names = ['stationTime','rollingPowerAvg'])
            self.sourcefile['stationTime'] = pd.to_datetime(self.sourcefile['stationTime'])
            self.sourcefile.index = self.sourcefile['stationTime']
            try:
                self.tStart = auth_config['tStart']
            except:
                self.tStart = None
            try:
                self.Ts = auth_config['Ts']
            except:
                self.Ts = 60
#         return client

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
        if self.mode == 'db':
            try: self.cursor.close()
            except: pass
        self.logger.info('DeviceThread terminating')
        
    def get_plug(self):
        return self.plug
        
    
    def getStationStatus(self):
        '''
        Get the current status of a charge station/ group of stations
        :return: the station data as a list of dictionaries
        :rtype: list
        '''
        search_query = {}
        if (self.stationID is not None):
            search_query["stationID"] = self.stationID
        try:
            res = self.client.service.getStationStatus(search_query)
        except Exception as e:
            print("Unable to getStationStatus data %s" % e)
            return None
        else:
            return res.stationData

    def getStations(self):
        '''Get information about the particular station or all stations in a list
        :return: the station data as a list of dictionaries
        :rtype: list
        '''
        search_query = {}
        try:
            if (self.sgID is not None):
                search_query["sgID"] = self.sgID
        except AttributeError:
            pass
        try:
            if (self.stationID is not None):
                search_query["stationID"] = self.stationID
        except AttributeError:
            pass

        try:
            res = self.client.service.getStations(search_query)
        except Exception as e:
            print("Unable to getStations data : %s" % e)
            return None
        else:
            return res.stationData
    
    def getLoad(self):
        '''Get load in kW of ports, shedState etc.
        :return: the load data as a dictionary
        :rtype: dict
        '''
        search_query = {}
        try:
            if (self.sgID is not None):
                search_query["sgID"] = self.sgID
            else:
                print("Required attribute sgID is missing")
        except AttributeError:
            pass
        else:
            return
        try:
            if (self.stationID is not None):
                search_query["stationID"] = self.stationID
        except AttributeError:
            pass
        try:
            res = self.client.service.getLoad(search_query)
        except Exception as e:
            print("Unable to getLoad data : %s" % e)
            return None
        else:
            return res
    
    '''
    def shedLoad(self, percent_amount=0, absolute_amount=0, time_interval=0):
        shed_query = {}
        # if station parameters present, construct the more restrictive query 
        if (self.stationID is not None):
            station_query = {"stationID": self.stationID}
            if (len(self.ports) > 0) and (type(percent_amount) is dict or type(absolute_amount) is dict):
                station_query["Ports"] = []
                for port in self.ports:
                    port_query = {"portNumber": port['portID']}
                    if port['portID'] in absolute_amount.values():
                        port_query["allowedLoadPerPort"] = absolute_amount[port['portID']]
                    else:
                        # ns0:percentShedRange ??
                        port_query["percentShedPerPort"] = percent_amount[port['portID']]
                        station_query["Ports"].append({"Port": port_query})
            
            else:
            # construct a Station query
    # shed amount
                if ((absolute_amount is None) and (percent_amount is None)):
                    print("Both absolute_amount and Percent_amount cannot be None")
                    return None
            
                elif (absolute_amount is not None):
                    station_query["allowedLoadPerStation"] = absolute_amount
                else:
                    # ns0:percentShedRange??
                    station_query["percentShedPerStation"] = percent_amount
                    
            shed_query["shedStation"] = station_query
    
        else:
            # construct a more general stationGroup query
            shed_query["shedGroup"] = {"sgID": self.sgID}
    
    # shed amount
            if ((absolute_amount is None) and (percent_amount is None)):
                print("Both absolute_amount and Percent_amount cannot be None")
                return None
        
            elif (absolute_amount is not None):
                shed_query["allowedLoadPerStation"] = absolute_amount
            else:
                # ns0:percentShedRange??
                shed_query["percentShedPerStation"] = percent_amount
            
                # shed interval, 0 means no limit
        shed_query["timeInterval"] = time_interval
        try:
            res = self.client.service.shedLoad(shed_query)
        except Exception as e:
            print("Unable to shedLoad : %s" % e)
            return None
        else:
            return res
    # Shed a specific load on a port
    
    def clearShedState(self):
        search_query = {}
        if (self.sgID is not None):
            search_query["sgID"] = self.sgID
        else:
            print("Required attribute sgID is missing")
            return
        if (self.stationID is not None):
            search_query["stationID"] = self.stationID
        try:
            res = self.client.service.clearShedState(search_query)
        except Exception as e:
            print("Unable to clearShedState : %s" % e)
            return None
        else:
            return res.Success
    # Clear shed state and resume normal operations
    '''
    
    def getRealtimeData(self, qty):
        '''Get charging session information in real time mode from SOAP API 
        :param qty: list of quantities requested
        :type qty: list
        :return: the session data as a list of dictionaries
        :rtype: list
        '''
        usageSearchQuery = {}
        sessionIDlist = []
        resultlist = []
        
# look at an 8 hour widow from the current time stamp to get a list of running    sessions
        tStart = datetime.now().replace(second = 0, microsecond = 0)
        usageSearchQuery["toTimeStamp"] = tStart
        
        tEnd = tStart-timedelta(hours = 8)
        usageSearchQuery["fromTimeStamp"] = tEnd
        # Make api call to get the session IDs
        try:
            res = self.client.service.getChargingSessionData(usageSearchQuery)
        except Exception as e:
            self.logger.error("Unable to getChargingSessionData : %s" % e)
            return resultlist
        else:
# loop over the results and store the session IDs
            for d in res.ChargingSessionData:
                    sessionIDlist.append(d.sessionID)
# round up the starting time to the nearest 15 min interval and look at sessions that have begun since then
            windowEnd = tStart
            windowStart = tStart - timedelta(minutes= tStart.minute % 15, seconds = tStart.second,microseconds=tStart.microsecond)      
            # Call the 15 min session api using the list of session IDs
            for sessionID in sessionIDlist:
                data = self.client.service.get15minChargingSessionData(sessionID=sessionID)
                for d in data.fifteenminData:
                    # check if the session time is within the window
                    stationTime = datetime.strptime(datetime.strftime(d.stationTime,self.fmt),self.fmt)
                    if windowStart <= stationTime and stationTime <= windowEnd:
# store the results in a dictionary containing the queried values
                        results = {'stationID': data.stationID, 'portNumber': data.portNumber, 'sessionID': data.sessionID, 'stationTime' : d.stationTime}
                        for item in qty:
                            if item == 'all':
                                results['energyConsumed'] = d.energyConsumed
                                results['peakPower'] = d.peakPower
                                results['rollingPowerAvg'] = d.rollingPowerAvg
                            else:
                                try: value = getattr(d,item)
                                except: 
                                    self.logger.error("Queried quantity %s not found" % item)
                                    results[item] = 'NA'
                                else:
                                    results[item] = value
                        resultlist.append(results)
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
        elif self.mode == 'playbackCSV':
            results = self.getPlaybackDataCSV()
        return ['qry',results]
    
    def getPlaybackData(self, qty):
        ''' play data from a sql database and return the results
        :param qty: list of quantities requested
        :type qty: list
        :return: the session data as a list of dictionaries
        :rtype: list
        '''
        resultlist = []
        self.conn = sqlite3.connect(self.dbname)
        self.cursor = self.conn.cursor()
        results = {}
        
        if self.tStart is None:
            curr_time = datetime.strftime(datetime.now(), self.fmt)
            time_frags = ('%%'+curr_time[5:],'%%'+curr_time[5:7]+'__'+curr_time[-8:]+'%%','%%'+curr_time[-8:],'%%'+curr_time[-8:-3]+'%%','%%'+curr_time[-8:-5]+'%%')
            time_query = 'SELECT stationTime FROM fifteen_min_session WHERE (stationTime like ? or stationTime like ? or stationTime like ? or stationTime like ? or stationTime like ?) ORDER by stationTime'
            self.cursor.execute(time_query,time_frags)
            try:
                self.tStart = self.cursor.fetchone()[0]
            except:
                self.tStart = '2020-01-02 00:00:00'
            self.logger.info("returned time %s" % self.tStart)
            dt = datetime.strptime(self.tStart,self.fmt)
#             dt = dt - timedelta(minutes= dt.minute % self.Ts, seconds = dt.second,microseconds=dt.microsecond)
            dt = dt + (datetime.min - dt) % timedelta(minutes = self.Ts)
            self.tStart = datetime.strftime(dt,self.fmt)
            self.logger.info(self.tStart)
            
            
        windowStart = self.tStart
        windowEnd = self.tStart
        search_query = 'SELECT * FROM fifteen_min_session WHERE stationTime BETWEEN ? AND ? GROUP by stationID,stationTime'
        self.cursor.execute(search_query,(windowStart, windowEnd))
        for row in self.cursor.fetchall():
            stationID, portNumber, sessionID, stationTime, energyConsumed, peakPower, rollingPowerAvg = row
            results = {'stationID': stationID, 'portNumber': portNumber, 'sessionID': sessionID, 'stationTime': stationTime}
            for item in qty:
                if item == 'all':
                    results['energyConsumed'] = energyConsumed
                    results['peakPower'] = peakPower
                    results['rollingPowerAvg'] = rollingPowerAvg
                else:
                    try: value = locals()[item]
                    except: 
                        self.logger.error("Queried quantity %s not found" % item)
                        results[item] = 'NA'
                    else:
                        results[item] = value
            resultlist.append(results)
            
        if len(resultlist) == 0:
            results['stationTime']= self.tStart
            results['rollingPowerAvg']= 0
            resultlist.append(results)
        self.tStart = datetime.strftime(datetime.strptime(self.tStart,self.fmt) + timedelta(minutes = self.Ts),self.fmt)
        self.cursor.close()
        return resultlist
    
    def getPlaybackDataCSV(self):
        ''' play data from a csv and return the results
        :param qty: list of quantities requested
        :type qty: list
        :return: the session data as a list of dictionaries
        :rtype: list
        '''
        resultlist = []
        results = {}
        
        if self.tStart is None:
            self.tStart = datetime.now()-relativedelta(years=1)
            self.tStart = self.tStart.replace(minute = 0, second = 0, microsecond = 0)
            self.tStart = datetime.strftime(self.tStart, self.fmt)
            
        try:
            results = self.sourcefile.loc[self.tStart]
            results = results.to_dict()
            results['stationTime'] = datetime.strftime(results['stationTime'], self.fmt)
        except KeyError:
            results = {'stationTime': self.tStart, 'rollingPowerAvg' : 0}
        
        resultlist.append(results)
        self.tStart = datetime.strftime(datetime.strptime(self.tStart,self.fmt) + timedelta(minutes = self.Ts),self.fmt)
        
        return resultlist
            
        
        


class ChargerInterface(Component):

# riaps:keep_constr:begin
    def __init__(self, configfile):
        super(ChargerInterface, self).__init__()
        self.DeviceThread = None
        self.identity = Queue()
        self.configfile = configfile
# riaps:keep_constr:end

# riaps:handle_act:begin
    def handleActivate(self):
        self.DeviceThread = ChargerInterfaceThread(self.configfile,self.relay,self.logger) # Inside port, external zmq port
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
        self.logger.info('exiting')
        self.DeviceThread.terminate()
        self.DeviceThread.join()

# riaps:keep_impl:end