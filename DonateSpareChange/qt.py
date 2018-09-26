import sys, os, time

from PyQt5.QtGui import *
from PyQt5.QtCore import *
from PyQt5.QtWidgets import *

from electroncash.address import Address
from electroncash.i18n import _
from electroncash.plugins import BasePlugin, hook
from electroncash.util import PrintError


class Plugin(BasePlugin):
    
    def __init__(self, parent, config, name):
        super().__init__(parent, config, name)
        self.instances = list() # list of 'Instance' objects
        self.gui = None # pointer to Electrum.gui singleton
        self.config = config
        
    def shortName(self):
        return _("Donate Change")
    
    def icon(self):
        from .resources import qInitResources # lazy importing
        return QIcon(":DonateSpareChange/resources/icon.png")

    def iconLarge(self):
        from .resources import qInitResources # lazy importing
        return QIcon(":DonateSpareChange/resources/icon64.png")

    def description(self):
        return _("Automatically donate change outputs to charities (or any address) of our choice, to protect your privacy and also go good!")
    
    def thread_jobs(self):
        return list()
    
    def on_close(self):
        """
        BasePlugin callback called when the wallet is disabled among other things.
        """
        ct = 0
        for instance in self.instances:
            instance.close()
            ct += 1
        self.instances = list()
        self.print_error("on_close: closed %d extant instances" % (ct) )


    @hook
    def init_qt(self, qt_gui):
        """
        Hook called when a plugin is loaded (or enabled).
        """
        self.gui = qt_gui
        # We get this multiple times.  Only handle it once, if unhandled.
        if len(self.instances):
            return

        # These are per-wallet windows.
        for window in self.gui.windows:
            self.load_wallet(window.wallet, window)
        
    @hook
    def load_wallet(self, wallet, window):
        """
        Hook called when a wallet is loaded and a window opened for it.
        """
        self.instances.append(Instance(self, wallet, window))
            
    @hook
    def close_wallet(self, wallet):
        for instance in self.instances:
            if instance.wallet == wallet:
                instance.close()
                self.instances.remove(instance) # pop it from the list of instances, python gc will remove it
                self.print_error("removed instance:", instance.objectName())
                return 

class Instance(QWidget, PrintError):
    def __init__(self, plugin, wallet, window):
        super().__init__()
        self.plugin = plugin
        self.wallet = wallet
        self.window = window
        self.wallet_name = os.path.split(wallet.storage.path)[1]
        self.setObjectName(self.plugin.shortName() + " (wallet='" + self.wallet_name + "')")
        # do stuff to setup UI...
        grid = QGridLayout(self)
        l = QLabel()
        l.setPixmap(plugin.iconLarge().pixmap(64, 64))
        grid.addWidget(l,0,0)
        grid.addWidget(QLabel(_("Donate Spare Change")), 0, 1)
        grid.addWidget(QLabel(_("Hello World!")), 1, 0)
        grid.addWidget(QLabel(_("La la la!")), 1, 1)
        window.tabs.addTab(self, plugin.icon(), plugin.shortName())
    
    # Uncomment to test object lifetime and make sure Qt is deleting us.
    #def __del__(self):
    #    print("**** __del__ ****")            

    def close(self):
        self.print_error("Close called on",self.objectName())
        if self.window:
            ix = self.window.tabs.indexOf(self)
            if ix > -1:
                self.window.tabs.removeTab(ix)
                self.deleteLater() # since qt doesn't delete us, we need to explicitly delete ourselves, otherwise the QWidget lives around forever in memory
        self.window, self.plugin, self.wallet, self.wallet_name = (None,) * 4

        
        

