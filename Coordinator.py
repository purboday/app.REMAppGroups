# riaps:keep_import:begin
from riaps.run.comp import Component
import spdlog
import capnp
import remapp_capnp
from array import array
import pulp as plp
from pulp.constants import LpMinimize
from pulp.apis.cplex_api import CPLEX_PY
import docplex.mp.model as cpx
from math import exp
import yaml
from datetime import datetime
import numpy as np
import random
import time

# riaps:keep_import:end

class Coordinator(Component):
    '''
    Coordinator RIAPS Component: It receives the current and future predicted power
    consumption information from the device managers and runs an optimization algorithm
    to determine the optimal power to be dispatched to the individual managers. It then
    sends the dispatch commands to the managers.
    '''

# riaps:keep_constr:begin
    def __init__(self,configfile, id, grptype):
        '''
        Constructor method
        :param configfile: name of the yaml file containing the influxdb tables details
        :type configfile: str   
        '''
        super(Coordinator, self).__init__()
        self.futureTimeStep = 24
        self.Psupply = [1000]*24
        self.purchasedPower = [1000]*24
        self.reqMap = {}
        self.dspMap = {}
        self.logger.info('the coordinator component starts')
        
        #commands from GUI
        self.microgridMode = 0
        self.gridPowerMode = 0
        self.gridPower = 1000
        self.weightBuilding = 1
        self.weightEv = 1
        
                
        self.Pbuilding = 0
        self.Pev = 0
        self.Pbattery = 0
        self.SoCbattery = 0
        
        self.Pred_building= 0
        self.Disp_building = 0
        self.Pred_ev= 0
        self.Disp_ev = 0
        self.Disp_battery = 0       
        
        self.gridPower24ahead = 0
        
        self.Ts = 60 * 60
        _config = "config/" + configfile
        with open(_config, 'r') as stream:
            try:
                table_config= yaml.safe_load(stream)
            except yaml.YAMLError as exc:
                print(exc)
        self.table_struct = table_config['table_struct']
        self.grpType = grptype.split(',')
        self.ready = False
        self.ID = id
        self.groups = {}
        
# riaps:keep_constr:end

    def handleActivate(self):
        for groupname in self.grpType:
            group = self.joinGroup(groupname, self.ID[:-1])
            self.groups[groupname] = group
            self.logger.info("joined group[%s]: %s" % (group.getGroupName(),str(group.getGroupId())))
            
    def sendEventData(self, entry):
        now = time.strftime('%Y-%M-%D %H:%m:%s')
        msg = entry
        msg['timestamp'] = now
        self.EventData.send_pyobj(msg)

# riaps:keep_query:begin
    def on_reqPower(self):
        '''
        Handler for receiving power requests from the various managers.
        The incoming message format is (reqID,reqKind,reqTime,reqPower,currPower)
        reqID : ID of the individual unit requesting power
        reqKind : type of load {'BU' - Builings, 'EV' - EV Chargers, 'BESS" - Battery Units}
        reqTime : the current time step
        reqPower : the predicted power consumption for some future time horizon
        currPower : the power consumption at the current time step
        '''
        qry = self.reqPower.recv_pyobj()
#         self.logger.info("received query : %s" % str(qry))
        (reqID,reqKind,reqTime,reqPower,currPower) = qry         
        reqClient= reqID[:-1]
        for gname, g in self.groups.items():
            self.logger.info('*********EVENT: Received Consumption Data, GROUP: %s, ID: %s, SenderID: %s*********' %(g.getGroupName(), self.ID, reqID))
            self.sendEventData({'Event': 'ReqPower', 'Group': g.getGroupName(), 'ID' : self.ID, 'For' : reqID})
            
        if reqClient in self.reqMap:
            self.logger.info("!!!!!! %s already exists!!!!!!" % reqID)
        self.reqMap[reqClient] = (reqKind, reqPower, reqTime, currPower)
        
        assert len(self.reqMap) <= 3
        
        print(self.reqMap)
        print(len(self.reqMap))
        
        if len(self.reqMap) == 3:
            sumReqPower = 0
            #purchase power for 24 time steps later
            for reqClient, request in self.reqMap.items():
                if (request[0] == 'BU') or (request[0] == 'EV'):
                    sumReqPower = request[1][-1] + sumReqPower
                    
            self.purchasedPower.append(sumReqPower)
            self.purchasedPower.pop(0)
            print(self.purchasedPower)
            
            for gname, g in self.groups.items():
                if g.isLeader() or g.groupSize() <= 2:
                    self.logger.info('*********EVENT: Begin Optimization, GROUP: %s, ID: %s*********' %(g.getGroupName(), self.ID))
                    self.sendEventData({'Event': 'Optimzation', 'Group': g.getGroupName(), 'ID' : self.ID, 'For' : self.ID})
                    self.predictiveDispatchQP()
                    for client, values in self.dspMap.items():
                        self.dspPower.send_pyobj(self.dspMap[client])
                        self.logger.info('*********EVENT: Sent Dispatched Power, GROUP: %s, ID: %s*********' %(g.getGroupName(), self.ID))
                        self.sendEventData({'Event': 'SendPower', 'Group': g.getGroupName(), 'ID' : self.ID, 'For' : client})
                    self.reqMap = {}
                elif not g.isLeader():
                    self.logger.info("not a leader %s" % self.ID)
                    self.reqMap = {}
                    
                else:
                    self.logger.info("group not ready")
                    self.tick.setDelay(5.0)
                    self.tick.launch()
# riaps:keep_query:end

    def on_tick(self):
        now = self.tick.recv_pyobj()
        for gname, g in self.groups.items():
            if g.isLeader() or g.groupSize() <= 2:
                self.tick.halt()
                self.logger.info('*********EVENT: Begin Optimization, GROUP: %s, ID: %s*********' %(g.getGroupName(), self.ID))
                self.sendEventData({'Event': 'Optimzation', 'Group': g.getGroupName(), 'ID' : self.ID, 'For' : self.ID})
                self.predictiveDispatchQP()
                for client, values in self.dspMap.items():
                    self.dspPower.send_pyobj(self.dspMap[client])
                    self.logger.info('*********EVENT: Sent Dispatched Power, GROUP: %s, ID: %s*********' %(g.getGroupName(), self.ID))
                    self.sendEventData({'Event': 'SendPower', 'Group': g.getGroupName(), 'ID' : self.ID, 'For' : client})
                    
                self.reqMap = {}
            elif not g.isLeader():
                self.logger.info("not a leader %s" % self.ID)
                        
            else:
                self.logger.info("group not ready")
                self.tick.setDelay(5.0)
                self.tick.launch()
        
                
    def handleLeaderElected(self, group, leaderId):
        assert (group in self.groups.values())
        self.logger.info('*********EVENT: Leader Elected, GROUP: %s, ID: %s*********' %(group.getGroupName(), self.ID))
        self.sendEventData({'Event': 'LeaderElected', 'Group': group.getGroupName(), 'ID' : self.ID, 'For' : leaderId})
        self.ready = True
        
    def handleLeaderExited(self, group, leaderId):
        assert (group in self.groups.values())
        self.logger.info('*********EVENT: Leader Left, GROUP: %s, ID: %s, LeaderID: %s*********' %(group.getGroupName(), self.ID, leaderId))
        self.sendEventData({'Event': 'LeaderLeft', 'Group': group.getGroupName(), 'ID' : self.ID, 'For' : leaderId})
        self.ready = False
        
    def handleMemberLeft(self,group,memberId):
        assert (group in self.groups)
        self.logger.info('*********EVENT: Member Left, GROUP: %s, ID: %s, MemberID: %s*********' %(group.getGroupName(), self.ID, memberId))
        self.sendEventData({'Event': 'MemberLeft', 'Group': group.getGroupName(), 'ID' : self.ID, 'For' : memberId})

# riaps:keep_gridpower:begin
    def on_power(self):
        '''
        receive commands from GUI
        commands include
        1. mode selection : 0 - grid connected mode; 1 - islanded mode
        2. grid power mode (only valid in grid connected mode): 0 - power purchased 24 hours ahead; 1 - constant grid power
        3. grid power (only valid in grid connected and constant grid power mode)
        4. weight for building in the optimization algorithm (default to 1)
        5. weight for EV in the optimization algorithm (default to 1)     
        '''
        ts, val = self.power.recv_pyobj()
        self.logger.info('grid commands received at %s : %s' % (str(ts), str(val)))
        for gname, g in self.groups.items():
            self.logger.info('*********EVENT: Received Grid Data, GROUP: %s, ID: %s*********' %(g.getGroupName(), self.ID))
            self.sendEventData({'Event': 'GridData', 'Group': g.getGroupName(), 'ID' : self.ID, 'For' : self.ID})
#       mode selection 
        self.microgridMode = val['microgridMode']
        self.gridPowerMode = val['gridPowerMode']
        self.gridPower = val['gridPower']
        self.weightBuilding = val['weightBuilding']
        self.weightEv = val['weightEv']

# riaps:keep_gridpower:end

# riaps:keep_loadpred:begin
    def on_loadPred(self):
        pass
# riaps:keep_loadpred:end
    
    def on_timeStepClock(self):
    
    #get updated data
    
    #    self.Psupply = [1000]*24
    
    
    # do the optimization
    
    #send out commands
        
        pass
        
        
    def predictiveDispatchQP(self):
        ''' Run an optimization algorithm on the entire prediction horizon.
            The optimization problem is formulated as a Linear Programming problem
            of the form: min_x(i,j) Sum_i,j 0.5 * (Power_Requested(i,j) - x(i,j))^2, where
            i = {1,2,... number of loads}, j = {1,2,... K} prediction horizon
            The constraints are given by Sum_i(x(i,j) <= b_j) for all j, where
            A =I in this case,
            b_j = Power available from the grid for all j
            x(i,j) >= 0
            x(i,j)) <= Power_Requested(i,j)
            :returns: the dispatch solution
            :rtype: dict
        '''
#         initialize the LP        
        optModel = cpx.Model(name='power_allocation')
            
#         define the decision variables
        set_I = range(1,len(self.reqMap)+1)
        set_J = range(1, self.futureTimeStep + 1)
        clientMap = {}
        weightMap = {}
#         lower bound is zero for total shedding  (except bess)      
        l = {(i,j): 0 for i in set_I for j in set_J}
#         initialize dict to store upper limit
        u = {(i,j): 0 for i in set_I for j in set_J}

        idx = 1
        for client in self.reqMap.keys():
            clientMap[idx] = client
            if self.reqMap[client][0] == 'BU':
                keyBU = client
#               weightMap[idx] = 1            
                for j in set_J:
#                   # grid-connected mode optimiza over the next 24 hours
                    if (self.microgridMode==0):
                        weightMap[idx,j] = exp(-(j-1)/8) * self.weightBuilding
                    # islanded mode optimiza over the next 4 hours
                    elif (self.microgridMode==1):
                        weightMap[idx,j] = exp(-(j-1)/1.5) * self.weightBuilding
                    #upper bound is the power requested
                    u[idx,j]= self.reqMap[clientMap[idx]][1][j-1]                      
            elif self.reqMap[client][0] == 'EV':
                keyEV = client
#               weightMap[idx] = 1
                for j in set_J:
                    # grid-connected mode optimiza over the next 24 hours
                    if (self.microgridMode==0):
                        weightMap[idx,j] = exp(-(j-1)/8) * self.weightEv
                    # islanded mode optimiza over the next 4 hours
                    elif (self.microgridMode==1):
                        weightMap[idx,j] = exp(-(j-1)/1.5) * self.weightEv
#         upper bound is the power requested
                    u[idx,j]= self.reqMap[clientMap[idx]][1][j-1]               
            elif self.reqMap[client][0] == 'BESS':
                keyBatt = client
                weightMap[idx] = 1
#         the bounds    are the power rating (signs indicate charging/ discharging)
                for j in set_J:
                    l[idx,j] = -1 * float(self.reqMap[client][1]['Rbess'])
                    u[idx,j] = float(self.reqMap[client][1]['Rbess'])
            else:
                weightMap[idx] = 1
            
            idx += 1

            
        
        x_vars  = {(i,j):
                   optModel.continuous_var( lb=l[i,j], 
                                             ub=u[i,j], 
                                             name="x_{0}_{1}".format(i,j)) 
                   for i in set_I for j in set_J}
#define the constraints
        # Less than equal constraints for grid power
        if self.microgridMode == 0:
            # grid-connceted mode with power purchase 1 day ahead
            if self.gridPowerMode == 0:
                self.Psupply = self.purchasedPower
            # grid-connceted mode with constant grid power
            elif self.gridPowerMode == 1:
                self.Psupply = [self.gridPower]*24
        # islanded mode  grid power is zero
        elif self.microgridMode == 1:
            self.Psupply = [0]*24
        
        b  = {j: self.Psupply[j-1] for j in set_J}
        constraints = {j : optModel.add_constraint(
            ct=optModel.sum(x_vars[i,j] for i in set_I) <= b[j],
            ctname="constraint_{0}".format(j))
            for j in set_J}
        
#         add battery SoC constraints
        for idx, client in clientMap.items():
            if self.reqMap[client][0] == 'BESS':
                for j in set_J:
                    constraints[list(set_J)[-1]+j] = optModel.add_constraint(
                        ct=optModel.sum(x_vars[idx,k]/float(self.reqMap[client][1]['Cbattery']) for k in range(1,j+1)) + float(self.reqMap[client][1]['SoC']) <= self.reqMap[client][1]['SoCu'],
                        ctname="constraint_bessu_{0}".format(j))
                    
                    constraints[2*list(set_J)[-1]+j] = optModel.add_constraint(
                        ct=optModel.sum(x_vars[idx,k]/float(self.reqMap[client][1]['Cbattery']) for k in range(1,j+1)) + float(self.reqMap[client][1]['SoC']) >= self.reqMap[client][1]['SoCl'],
                        ctname="constraint_bessl_{0}".format(j))
                
                constraints[3*list(set_J)[-1]+1] = optModel.add_constraint(
                        ct=optModel.sum(x_vars[idx,j]/float(self.reqMap[client][1]['Cbattery']) for j in set_J) + float(self.reqMap[client][1]['SoC']) == self.reqMap[client][1]['SoCend'],
                        ctname="constraint_besseq_{0}".format(j))
#         define the objective function
        objective = optModel.sum(0.5*(weightMap[i,j]*(self.reqMap[clientMap[i]][1][j-1] - x_vars[i,j])**2) 
                              for i in (k for k in set_I if self.reqMap[clientMap[k]][0] != 'BESS') 
                              for j in set_J)
        optModel.minimize(objective)
        
#         solve the model
        optModel.solve()
        
#         print objective function value
        self.logger.info('status: %s' % optModel.solve_details.status)
        self.logger.info('objective value: %f' % optModel.objective_value)
        self.optVal = optModel.objective_value
        
#         store the results
        for idx, client in clientMap.items():
            keylist = [(idx,j) for j in set_J]
            #self.dspMap[client] = (self.reqMap[client][0], array('f',[x_vars[k].solution_value for k in keylist]))
            self.dspMap[client] =  (self.reqMap[client][0], [x_vars[k].solution_value for k in keylist])
        self.logger.info('dispatch results: %s' % str(self.dspMap))
        
        initialSoC = float(self.reqMap[keyBatt][1]['SoC'])
        FinalSoC = sum(self.dspMap[keyBatt][1])/1000 + initialSoC
        self.logger.info('initial %s and predicted final SoC %s' % (str(initialSoC),str(FinalSoC)))
        
        self.SoCbattery = initialSoC
        self.Pbuilding = self.reqMap [keyBU][3]
        self.Pev = self.reqMap [keyEV][3]
        self.Pbattery = self.reqMap [keyBatt][3]
        self.Pred_building = self.reqMap [keyBU][1]
        self.Disp_building =  self.dspMap[keyBU][1]
        self.Pred_ev = self.reqMap [keyEV][1]
        self.Disp_ev = self.dspMap [keyEV][1]
        self.Disp_battery = self.dspMap[keyBatt][1]
        self.gridPower24ahead = self.Psupply
        
        #self.writeDownTestValues()
        self.log()
        
    def writeDownTestValues(self):
        # actual power comsumption for the last time steps( Pbuilding, Pev, Pbattery) and Battery SoC 
        # building prediction for the next 24 time steps
        #  and buidling dispatched power for the next 24 time steps 
        # ev prediction for the next 24 time steps       
        #  and ev dispatched power for the next 24 time steps
        # battery dispatched power for the next 24 time steps
        # gridPower constrant which should be set to predictio made by 24 time step ahead
        
        try:          
            filename = "actualPAndSoC"
            file = open(filename, "a")
            file.write(str(self.Pbuilding)+'     ' + str(self.Pev)+'     ' + str(self.Pbattery)+'     '+ str(self.SoCbattery) +'\n')
            file.close()
            
            filename2 = "buildingPredictionAndDispatch"
            file2 = open(filename2, "a")
            file2.write(str(self.Pred_building) +'\n'+ str(self.Disp_building) + '\n')
            file2.close()
            
            filename3 = "evPredictionAndDispatch"
            file3 = open(filename3, "a")
            file3.write(str(self.Pred_ev) +'\n' + str(self.Disp_ev) + '\n')
            file3.close()
            
            filename4 = "batteryDispatch"
            file4 = open(filename4, "a")
            file4.write(str(self.Disp_battery) + '\n')
            file4.close()

            filename5 = "gridPower"
            file5 = open(filename5, "a")
            file5.write(str(self.gridPower24ahead) + '\n')
            file5.close()
     
        except UnboundLocalError:
            pass    
            
            
    def predictiveDispatch(self):
#         initialize the LP        
        optModel = plp.LpProblem(name='power_allocation', sense=LpMinimize)
        
        # i is the set for different devices
        set_I = range(1,len(self.reqMap)+1) 
        # j is the set for different time steps
        set_J = range(1, self.futureTimeStep + 1)
        clientMap = {}
        idx = 1
        for client in self.reqMap.keys():
            clientMap[idx] = client
            idx += 1
            
#         lower bound is zero for total shedding
        l = {(i,j): 0 for i in set_I for j in set_J}
#         upper bound is the power requested
        u = {(i,j): self.reqMap[clientMap[i]][1][j-1] for i in set_I for j in set_J}
#         create variables
        x_vars  = {(i,j):
                   plp.LpVariable(cat=plp.LpContinuous, 
                                  lowBound=l[i,j],
                                  upBound=u[i,j], 
                                  name="x_{0}_{1}".format(i,j)) 
                   for i in set_I for j in set_J}
#         define the constraints
        # Less than equal constraints for total energy dispatch
        b  = {j: self.Psupply[j-1] for j in set_J}
        constraints = {j : optModel.addConstraint(
            plp.LpConstraint(
                e=plp.lpSum(x_vars[i,j] for i in set_I),
                sense=plp.LpConstraintLE,
                rhs=b[j],
                name="constraint_{0}".format(j)))
            for j in set_J}
#         define the objective function
        objective = plp.lpSum((self.reqMap[clientMap[i]][1][j-1] - x_vars[i,j])
                              for i in set_I 
                              for j in set_J)
        optModel.setObjective(objective)
#         solve the model
        status = optModel.solve(solver = CPLEX_PY())
#         print objective function value
        self.logger.info('status: %s' % plp.LpStatus[status])
        self.logger.info('objective value: %f' % optModel.objective.value())
#         store the results
        for idx, client in clientMap.items():
            keylist = [(idx,j) for j in set_J]
            self.dspMap[client] = (self.reqMap[client][0], array('f',[x_vars[k].value() for k in keylist]))
        self.logger.info('dispatch results: %s' % str(self.dspMap))

# riaps:keep_impl:begin

    def log(self):
            '''
            Send message to logger
            The log data sent to the logger needs to be a list of tuples.
            Each tuple is of the format (tags, measurement, timestamps, values)
            tags : dictionary containing the tag column names and their values
            measurement : name of the measurement (table in InfluxDB) where the values will be stored
            timestamps : list of timestamps corresponding to each value
            values: list of dictionaries where each dictionary is {column_name : value}
            '''
            datastream = []
            # write actual power
            for id, details in self.reqMap.items():
                tags = {}
                curr_stamp = datetime.strptime(details[2], '%Y-%m-%d %H:%M:%S')
                curr_stamp = curr_stamp.timestamp()
                try : tagl = len(self.table_struct['ActualPower']['tags'])
                except: pass
                else:
                    self.logger.info('tagl = %d' % tagl)
                    if tagl == 2:
                        tags[self.table_struct['ActualPower']['tags'][0]] = details[0]
                        tags[self.table_struct['ActualPower']['tags'][1]] = id
                        self.logger.info(str(tags))
                values = [{self.table_struct['ActualPower']['value']: float(details[3])}]
                stamps = [(curr_stamp + i * self.Ts) for i in range(len(values))]
                datastream.append((tags,self.table_struct['ActualPower']['measurement'],stamps,values))
                
            # write predicted power
                if details[0] != 'BESS':
                    tags = {}
                    try : tagl = len(self.table_struct['PredictedPower']['tags'])
                    except: pass
                    else:
                        if tagl == 2:
                            tags[self.table_struct['PredictedPower']['tags'][0]] = details[0]
                            tags[self.table_struct['PredictedPower']['tags'][1]] = id
                    values = [{self.table_struct['PredictedPower']['value']: float(details[1][i])} for i in range(len(details[1]))]
                    stamps = [(curr_stamp + i * self.Ts) for i in range(len(values))]
                    datastream.append((tags,self.table_struct['PredictedPower']['measurement'],stamps,values))
                
                
            # write dispatched power
                tags = {}
                try : tagl = len(self.table_struct['DispatchedPower']['tags'])
                except: pass
                else:
                    if tagl == 2:
                        tags[self.table_struct['DispatchedPower']['tags'][0]] = details[0]
                        tags[self.table_struct['DispatchedPower']['tags'][1]] = id
                values = [{self.table_struct['DispatchedPower']['value']: float(self.dspMap[id][1][i])} for i in range(len(self.dspMap[id][1]))]
                stamps = [(curr_stamp + i * self.Ts) for i in range(len(values))]
                datastream.append((tags,self.table_struct['DispatchedPower']['measurement'],stamps,values))
                
            # write battery SoC
                if details[0] == 'BESS':
                    tags = {}
                    values = [{self.table_struct['SoC']['value']: float(self.SoCbattery)}]
                    try : tagl = len(self.table_struct['SoC']['tags'])
                    except: pass
                    else:
                        if tagl == 1:
                            tags[self.table_struct['SoC']['tags'][0]] = id
                    stamps = [(curr_stamp + i * self.Ts) for i in range(len(values))]
                    datastream.append((tags,self.table_struct['SoC']['measurement'],stamps,values))
                        
        # write grid power
            tags = {}
            values = [{self.table_struct['Grid']['value'] : float(self.gridPower24ahead[i])} for i in range(len(self.gridPower24ahead))]
            stamps = [(curr_stamp + i * self.Ts) for i in range(len(values))]
            datastream.append((tags,self.table_struct['Grid']['measurement'],stamps,values))
            
            total_dsp = np.zeros(24)
            
            for client, data in self.dspMap.items():
#                 if data[0] == "BU" or data[0] == "EV":
                total_dsp += np.array(data[1])
                
            tags = {}
            values = [{self.table_struct['AggregatePower']['value'] : float(total_dsp[i])} for i in range(len(total_dsp))]
            stamps = [(curr_stamp + i * self.Ts) for i in range(len(values))]
            datastream.append((tags,self.table_struct['AggregatePower']['measurement'],stamps,values))

#             msg = (tag,meas,stamps,values)
            self.logData.send_pyobj(datastream)
# riaps:keep_impl:end