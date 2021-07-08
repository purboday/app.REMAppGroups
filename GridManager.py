# riaps:keep_import:begin
from riaps.run.comp import Component
import spdlog
import capnp
import remapp_capnp

# riaps:keep_import:end

class GridManager(Component):
    def __init__(self):
        super(GridManager, self).__init__()
        self.logger.info("GridManager - starting")
        
    def on_setPoint(self):
        msg = self.setPoint.recv_pyobj()
        self.logger.info("forwarding grid set points")
        self.power.send_pyobj(msg)