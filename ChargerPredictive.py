from riaps.run.comp import Component
import tensorflow as tf
import pandas as pd
import numpy as np
from pandas.tseries.holiday import USFederalHolidayCalendar


class ChargerPredictive(Component):

# riaps:keep_constr:begin
    def __init__(self,model_path):
        super(ChargerPredictive, self).__init__()
        self.predictor = chargerPredictor(self.logger, model_path)
        
        self.logger.info("starting predictive model device with id %s " % str( id (self.predictor)) )
# riaps:keep_constr:end

# riaps:updateAndPredict:begin
    def on_updateAndPredict(self):
        msg = self.updateAndPredict.recv_pyobj()
        msg_id = self.updateAndPredict.get_identity()
        self.logger.info("received from manager: %s" % str(msg))
        
        self.predictor.run(msg)
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




class chargerPredictor():
    def __init__(self,logger,model_path):
        self.historyStep = 24
        self.futureStep = 24
        self.logger = logger
        self.historyInput = None
        self.futureInput = None
        self.ini = True
        self.holiday_gen  = USFederalHolidayCalendar()
        self.prediction = 0
        self.model_path = 'models/'+model_path
        self.avePower = 46.6291095890411
        self.stdPower = 92.6455346398567
        '''
        try:
            self.model = tf.keras.models.load_model(self.model_path)
        except:
            self.logger.info("Model does not exist at %s" % self.model_path )
        '''
        self.model = tf.keras.models.load_model(self.model_path,compile=False)
        
    def UpdateInput(self,msg):
        newDate = msg['Date']
        newPower = (msg['aggregatedPower'] - self.avePower )/self.stdPower
        
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
            self.historyInput = np.c_[np.zeros((h,1)), dayofWeekVector[-f-h:-f],holidayVector[-f-h:-f],hourOfdayVector[-f-h:-f] ]
            self.futureInput = np.c_[ dayofWeekVector[-f:],holidayVector[-f:],hourOfdayVector[-f:]]
            
            self.historyInput  = np.expand_dims(self.historyInput ,0)
            self.futureInput  = np.expand_dims(self.futureInput ,0)


        newHistoryInput = np.c_[newPower, self.futureInput[0,0,:].reshape(1,32)]
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
        self.prediction = self.model.predict(self.historyInput)
        self.prediction = self.prediction*self.stdPower + self.avePower
        
    def run(self,msg):
        self.UpdateInput(msg)
        self.predict()
           
if __name__ == '__main__':
    testob = chargerPredictor(1, 'ev_example_model.h5')
    msg = {'Date':'2019-01-01 11:00:00', 'aggregatedPower':5.6 }
    testob.UpdateInput(msg) 
    print(testob.historyInput)
    testob.predict()
    print(testob.prediction)