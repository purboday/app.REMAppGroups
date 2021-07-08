from riaps.run.comp import Component
import tensorflow as tf
import pandas as pd
import numpy as np
from pandas.tseries.holiday import USFederalHolidayCalendar


class BuildingPredictive(Component):

# riaps:keep_constr:begin
    def __init__(self,model_path):
        super(BuildingPredictive, self).__init__()
        self.predictor = buildingPredictor(self.logger, model_path)
        
        self.logger.info("starting predictive model device with id %s " % str( id (self.predictor)) )
# riaps:keep_constr:end

# riaps:updateAndPredict:begin
    def on_updateAndPredict(self):
        msg = self.updateAndPredict.recv_pyobj()
        msg_id = self.updateAndPredict.get_identity()
        self.logger.info("received from manager: %s" % str(msg))
        
        self.predictor.run(msg[0])
        predicitonResult = self.predictor.prediction
        self.logger.info("prediction for the next time step: %s" % str(predicitonResult))
        predicitonResult = np.squeeze (predicitonResult)
        predicitonResult = np.clip(predicitonResult, a_min=0, a_max=None)
        predicitonResult_list = predicitonResult.tolist()
        self.updateAndPredict.set_identity(msg_id)
        self.updateAndPredict.send_pyobj(predicitonResult_list)
    
    def __destroy__(self):
       self.logger.info("exiting predictive device")
       tf.keras.backend.clear_session()
# riaps:updateAndPredict:end




class buildingPredictor():
    def __init__(self,logger,model_path):
        self.historyStep = 48
        self.futureStep = 24
        self.logger = logger
        self.historyInput = None
        self.futureInput = None
        self.ini = True
        self.holiday_gen  = USFederalHolidayCalendar()
        self.prediction = 0
        self.model_path = 'models/'+model_path
        self.avePower = 794.228479
        self.stdPower = 282.101284
        self.aveOAT   = 61.722562
        self.stdOAT   = 10.996571
        '''
        try:
            self.model = tf.keras.models.load_model(self.model_path)
        except:
            self.logger.info("Model does not exist at %s" % self.model_path )
        '''
        self.model = tf.keras.models.load_model(self.model_path,compile=False)
        
    def UpdateInput(self,msg):
        newDate = msg['Date']
        try:
            newPower = (msg['HT_TotalPower'] - self.avePower )/self.stdPower
        except:
            newPower = (0 - self.avePower )/self.stdPower
        try:    
            newOAT = (msg['OutsideAirTemp']- self.aveOAT)/self.stdOAT
        except:
            newOAT = (0 - self.aveOAT)/self.stdOAT
        
        newDate = pd.to_datetime(newDate)
        oneHourDelta = pd.Timedelta('1 Hour')
        oneDayDelta  = pd.Timedelta('1 Day')
        
        if self.ini == True:
            dateList = []
            for i in range (7*24):
                dateItem = newDate - (6*24-i)*oneHourDelta
                dateList.append(dateItem)
            self.ini = False
            
            dateList = pd.to_datetime(dateList)
            
            dayOfWeekList = dateList.dayofweek.values
            dayofWeekVector = pd.get_dummies(dayOfWeekList)
            hourOfdayList = dateList.hour
            hourOfdayVector = pd.get_dummies(hourOfdayList)
            holidays = self.holiday_gen.holidays(start=dateList.min(), end=dateList.max())
            holidayVector = pd.to_datetime(dateList.date).isin(holidays).astype(int)
            holidayVector = holidayVector.reshape((168,1))

            h = self.historyStep
            f = self.futureStep
            self.historyInput = np.c_[np.zeros((h,2)), dayofWeekVector[-f-h:-f],holidayVector[-f-h:-f],hourOfdayVector[-f-h:-f] ]
            self.futureInput = np.c_[ dayofWeekVector[-f:],holidayVector[-f:],hourOfdayVector[-f:]]
            
            self.historyInput  = np.expand_dims(self.historyInput ,0)
            self.futureInput  = np.expand_dims(self.futureInput ,0)


        newHistoryInput = np.c_[newPower, newOAT, self.futureInput[0,0,:].reshape(1,32)]
        self.historyInput = np.r_[self.historyInput[0,1:,:], newHistoryInput]
        self.historyInput = np.expand_dims(self.historyInput,0)
        
        newPredictEndDate = newDate + oneDayDelta
        holidays = self.holiday_gen.holidays(start=(newDate-2*oneDayDelta), end=(newDate+2*oneDayDelta))
        newHoliday = pd.to_datetime([newPredictEndDate.date()]).isin(holidays).astype(int)
        newDayOfWeek = np.zeros((1,7))
        newHourofDay = np.zeros((1,24))
        newDayOfWeek[0,newPredictEndDate.dayofweek] =1
        newHourofDay[0,newPredictEndDate.hour]=1
        newFutureInput = np.c_[newDayOfWeek,newHoliday,newHourofDay]
        self.futureInput = np.r_[ self.futureInput[0,1:,:], newFutureInput ]
        self.futureInput = np.expand_dims(self.futureInput,0)
        
    def updateModel(self):
        pass
    
    def updateTrainingInput(self):
        pass
    
    def predict(self):
        self.prediction = self.model.predict([self.historyInput, self.futureInput])
        self.prediction = self.prediction*self.stdPower + self.avePower
        
    def run(self,msg):
        self.UpdateInput(msg)
        self.predict()
           
if __name__ == '__main__':
    testob = buildingPredictor(1, 'my_lstm_model.h5')
    msg = {'Date':'2019-09-01 11:00:00', 'HT_TotalPower':1926, 'OutsideAirTemp':76}
    testob.UpdateInput(msg) 
    print(testob.prediction)
    testob.predict()
    print(testob.prediction)