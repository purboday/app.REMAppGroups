# riaps:keep_import:begin
from riaps.run.comp import Component
import spdlog
import capnp
import remapp_capnp
import time

# riaps:keep_import:end

class BuildingManager(Component):
    '''
    EV Charger Manager RIAPS Component
    '''

# riaps:keep_constr:begin
    def __init__(self,id, grptype):
        '''
        Constructor method
        :param id: identifier for the individual load
        :type id: str
        '''
        super(BuildingManager, self).__init__()
        self.predition = 0
        self.logger.info("starting manager component")
        self.ID = id
        self.type = 'BU'
        self.msgTime = None
        self.currentPower = 0
        self.groups = {}
        self.grpType = grptype.split(',')
        self.ready = False
        self.myrfcID = None
        self.updatedData = None
        self.voteLib = {}
        self.waitforData = 0
        self.pendingVote = {}
# riaps:keep_constr:end

    def handleActivate(self):
        for groupname in self.grpType:
            group = self.joinGroup(groupname, self.ID[:-1])
            self.groups[groupname] = group
            self.logger.info("joined group[%s]: %s" % (group.getGroupName(),str(group.getGroupId())))

# riaps:keep_command:begin
    def on_command(self):
        pass
    def sendEventData(self, entry):
        now = time.strftime('%Y-%M-%D %H:%m:%s')
        msg = entry
        msg['timestamp'] = now
        self.EventData.send_pyobj(msg)
# riaps:keep_command:end

# riaps:keep_control:begin
    def on_dspPower(self):
        '''
        Message handler to receive dispatched power from Coordinator.
        Message format (type, powerGranted)
        type : type of load {'BU' - Builings, 'EV' - EV Chargers, 'BESS" - Battery Units}
        powerGranted : list of power values for the time horizon.
        '''
        ans = self.dspPower.recv_pyobj()
        type, powerGranted = ans
        if type == self.type:
            self.logger.info("received allocated power")
# riaps:keep_control:end

# riaps:keep_poller:begin
    def on_poller(self):
        '''
        Message handler for information received from device component.
        Message format is a list of dictionaries containing {qty : value} pairs
        and a datetime.
        The data is then sent to the predictive device component.
        Message format : [{'Date': str, 'Building_Unit: power (float)}]
        '''
        msg = self.poller.recv_pyobj()
        for gname, g in self.groups.items():
            self.logger.info('*********EVENT: Sensor Data Received, GROUP: %s, ID: %s*********' %(g.getGroupName(), self.ID))
            self.sendEventData({'Event': 'SensorData', 'Group': g.getGroupName(), 'ID' : self.ID, 'For' : self.ID})
        self.msgTime = msg[0]['Date']
        self.currentPower = msg[0]['HT_TotalPower']
        self.updatedData = msg
        # vote for consensus 
        self.tick.setDelay(1.0)
        self.tick.launch()         
# riaps:keep_poller:end

    def on_tick(self):
        now = self.tick.recv_pyobj()
        for gname, g in self.groups.items():
            if self.ready:
                self.myrfcID = g.requestVote_pyobj(self.updatedData) # Majority vote
                self.logger.info('*********EVENT: Begun Voting, GROUP: %s, ID: %s, RFCID: %s*********' %(g.getGroupName(), self.ID,self.myrfcID))
                self.sendEventData({'Event': 'VoteBegin', 'Group': g.getGroupName(), 'ID' : self.ID, 'For' : self.myrfcID})
                self.tick.halt()
            elif g.groupSize() <= 2:
                self.tick.halt()
                self.updateAndPredict.send_pyobj(self.updatedData)
            else:
                self.logger.info("no leader yet [%d]" % g.groupSize())
                self.tick.setDelay(1.0)
                self.tick.launch()
                
    def on_votetrigger(self):
        now = self.votetrigger.recv_pyobj()
        self.waitforData +=1
        if self.waitforData > 3 and self.updatedData is None:
            self.waitforData = 0
            vote = False
            for rfcId, msg in self.pendingVote.items():
                for gname, g in self.groups.items():
                    g.sendVote(rfcId,vote)
            self.pendingVote = {}
                    
        elif self.updatedData is not None:
            self.waitforData = 0
            for rfcId, msg in self.pendingVote.items():
                vote = abs(msg[0]['HT_TotalPower'] - self.updatedData[0]['HT_TotalPower'])/(self.updatedData[0]['HT_TotalPower']+1e-9) <= 0.05
                for gname, g in self.groups.items():
                    g.sendVote(rfcId,vote)
            self.pendingVote = {}
        else:
            self.logger.info("waiting for device data")
            self.votetrigger.setDelay(5.0)
            self.votetrigger.launch()

            
    def handleVoteRequest(self,group,rfcId):
        assert (group in self.groups.values())
        msg = group.recv_pyobj()
        vote = 'pending'
        if self.updatedData is not None:
            vote = abs(msg[0]['HT_TotalPower'] - self.updatedData[0]['HT_TotalPower'])/(self.updatedData[0]['HT_TotalPower']+1e-9) <= 0.05
            group.sendVote(rfcId,vote)
        else:
            self.pendingVote[rfcId] = msg
            self.votetrigger.setDelay(5.0)
            self.votetrigger.launch()    
#         self.logger.info('handleVoteRequest[%s] = %s -->  %s' % (str(rfcId),str(msg[0]['HT_TotalPower']), str(vote)))
        
    def handleVoteResult(self,group,rfcId,vote):
        assert (group in self.groups.values())
#         self.logger.info('handleVoteResult[%s] = %s ' % (str(rfcId),str(vote)))
        if rfcId   ==   self.myrfcID:
            self.logger.info('*********EVENT: Voting Result, GROUP: %s, ID: %s, RFCID: %s*********' %(group.getGroupName(), self.ID, rfcId))
            self.sendEventData({'Event': 'VoteEnd', 'Group': g.getGroupName(), 'ID' : self.ID, 'For' : rfcId})
        self.voteLib[rfcId] = str(vote)
        if len(self.voteLib) == group.groupSize()-1:
            if group.isLeader(): 
                if self.voteLib[self.myrfcID] == 'yes': 
                    self.logger.info("verified result is correct")
                    group.send_pyobj(self.myrfcID)
                else:
                    sent = False
                    for key in [key for key in self.voteLib if not key == self.myrfcID and self.voteLib[key] == 'yes']:
                        self.logger.info("asking other member to send data")
                        group.send_pyobj(key)
                        sent = True 
                        break
                    if not sent:
                        group.send_pyobj(self.myrfcID)
        else:
            self.logger.info("voteLib: %d entries" % len(self.voteLib))
                        
    def handleGroupMessage(self, group):
        assert (group in self.groups.values())
        msg = group.recv_pyobj()
        if msg == self.myrfcID:
            self.logger.info('*********EVENT: Send Consumption Data, GROUP: %s, ID: %s*********' %(group.getGroupName(), self.ID))
            self.sendEventData({'Event': 'SendReqPower', 'Group': group.getGroupName(), 'ID' : self.ID, 'For' : self.ID})
            self.updateAndPredict.send_pyobj(self.updatedData)
        self.voteLib = {}
        

# riaps:keep_trigger:begin
    def on_trigger(self):
        '''
        Timer handler that sends query message to the device component.
        Message format is a list of strings denoting the quantities to be queried.
        Quantities can be in {'all', 'TotalPower', 'HVAC', 'Temp', 'Lighting'}
        '''
        now = self.trigger.recv_pyobj()
        self.logger.info("sending query request")
        self.poller.send_pyobj(['TotalPower', 'HVAC', 'Temp'])

# riaps:keep_trigger:end

# riaps:keep_impl:begin
    def on_updateAndPredict(self):
        '''Message handler forincoming messages from the predictive device.
        Message format: list of power values for future time steps.
        It then sends a power query to the Coordinator component.
        Outgoing message format : (reqID,reqKind,reqTime,reqPower,currPower)
        reqID : ID of the individual unit requesting power
        reqKind : type of load {'BU' - Builings, 'EV' - EV Chargers, 'BESS" - Battery Units}
        reqTime : the current time step
        reqPower : the predicted power consumption for some future time horizon
        currPower : the power consumption at the current time step
        '''
        msg = self.updateAndPredict.recv_pyobj()
#         self.logger.info("prediction for the next time step: %s" % str(msg))
        powerReq = (self.ID, self.type, self.msgTime, msg, self.currentPower)
        for gname, g in self.groups.items():
            self.logger.info('*********EVENT: Send Consumption Data, GROUP: %s, ID: %s*********' %(g.getGroupName(), self.ID))
            self.sendEventData({'Event': 'SendReqPower', 'Group': g.getGroupName(), 'ID' : self.ID, 'For' : self.ID})
        self.reqPower.send_pyobj(powerReq)
        
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

# riaps:keep_impl:end

# riaps:keep_impl:end