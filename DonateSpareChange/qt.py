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
        self.setObjectName(self.diagnostic_name())
        self.data = self.DataModel(self, self.wallet.storage)

        # do stuff to setup UI...
        from .ui import Ui_Instance
        self.ui = Ui_Instance()
        self.ui.setupUi(self)

        self.c_mgr = self.CharitiesMgr(self, self.ui, self.data)        
        
        # finally, add the UI to the wallet window
        window.tabs.addTab(self, plugin.icon(), plugin.shortName())

    class CharitiesMgr(QObject, PrintError):
        def __init__(self, parent, ui, data):
            super().__init__(parent)
            self.parent = parent
            self.ui = ui
            self.data = data
            self.ui.tree_charities.setColumnWidth(0, 60)
            
            self.reload()

            # setup connections
            self.ui.tree_charities.itemSelectionChanged.connect(self.on_selection_changed) # charities selection changed
            self.ui.tree_charities.itemChanged.connect(self.on_item_changed) # charities item edited
            self.ui.tb_minus.clicked.connect(self.on_minus)
            self.ui.tb_plus.clicked.connect(self.on_plus)

        def diagnostic_name(self): # from PrintError
            return self.__class__.__name__ + "@" + self.parent.diagnostic_name() 


        def append_item(self, char_entry):
            en, name, address = char_entry
            item = QTreeWidgetItem(self.ui.tree_charities, ["", name, address])
            item.setFlags(item.flags() | Qt.ItemIsEditable)
            chk = QCheckBox()
            self.ui.tree_charities.setItemWidget(item, 0, chk)
            i = self.ui.tree_charities.topLevelItemCount()-1
            item.setData(0, Qt.UserRole, i)
            if en:
                chk.setChecked(True)   
            def on_chkd(b,chk=chk,name=name):
                self.print_error("Got chk from", chk, "=",b, "name=", name)
            chk.toggled.connect(on_chkd)

        def reload(self):
            self.ui.tree_charities.clear()
            chars = self.data.get_charities()
                   
            for char in chars:
                self.append_item(char)

            self.check_ok()
            
        def check_ok(self, item_changed = None):
            items = self.ui.tree_charities.findItems("", Qt.MatchContains, 0)
            allValid = True
            badBrush, goodBrush = QBrush(QColor("#BC1E1E")), QBrush()
            for i,item in enumerate(items):
                name, address = (item.text(1), item.text(2))
                #self.print_error("item ", i, "name=", name, "address=", address)
                if Address.is_valid(address):
                    item.setForeground(2, goodBrush)
                else:
                    item.setForeground(2, badBrush)
                    allValid = False
                    if item == item_changed:
                        item_changed.setSelected(False) # force it unselected so they see the error of their ways!
            self.ui.lbl_bad_address.setHidden(allValid)
                
            
        def on_selection_changed(self):
            self.ui.tb_minus.setEnabled(len(self.ui.tree_charities.selectedItems()))
        
        def on_item_changed(self, item, column):
            self.check_ok(item)
            
        def on_minus(self):
            items = self.ui.tree_charities.selectedItems()
            if items:
                msg = _("Do you really wish to delete these {} items?").format(len(items)) if len(items) > 1 else _("Do you really wish to delete this item?")
                if self.parent.window.question(msg=msg, title=_("Confirm Delete")):
                    root = self.ui.tree_charities.invisibleRootItem()
                    for item in items:
                        root.removeChild(item) # item will get gc'd by Python
                        
            self.check_ok()
    
        def on_plus(self):
            i = self.ui.tree_charities.topLevelItemCount() + 1
            self.append_item((False, "Charity #%d"%i, "Charity Address %d"%i))
            
        
    # nested class.. handles writing our data dict to/from persisten store
    class DataModel:
        def __init__(self, parent, storage):
            self.parent = parent
            self.storage = storage
            self.keys = {
                'root' : self.parent.plugin.name + "__Data__v00", # the root-level key that goes into wallet storage for all of our plugin data
                'charities' : 'charities', # the addresses, which ends up being a list of tuples (enabled, name, address_str)
                'change_def' : 'change_def', # the definition of what constitutes change, which is a simple tuple
                'initted' : 'initted', # boolean. if set, this data store has been initted before and doesn't need to get populated with defaults                
            }
                        
        def get_data(self):
            d = self.storage.get(self.keys['root'], dict())
            if not d.get('initted'):
                # initialize data with defaults
                charities = [
                    (True, "eatBCH", "pp8skudq3x5hzw8ew7vzsw8tn4k8wxsqsv0lt0mf3g"),
                    (True, "eatBCH_SS", "qrsrvtc95gg8rrag7dge3jlnfs4j9pe0ugrmeml950"),
                    (True, "Coins4Clothes", "qzx4tqcldmvs4up9mewkf3ru0z6vy9wm6qm782fwla"),
                    (False, "Calin", "qplw0d304x9fshz420lkvys2jxup38m9symky6k028"),
                ]
                change_def = (5000, 100, 0)
                d['charities'] = charities
                d['change_def'] = change_def
                d['initted'] = True
            return d

        def put_data(self, datadict, save=False):
            self.storage.put(self.keys['root'], datadict)
            if save: self.save()
            
        def save(self):
            self.storage.write()
    
        def get_charities(self):
            d = self.get_data()
            return d.get('charities', list())
            
        
    
    # Uncomment to test object lifetime and make sure Qt is deleting us.
    #def __del__(self):
    #    print("**** __del__ ****")            

    # called by self.plugin on wallet close - deallocate all resources and die.
    def close(self):
        self.print_error("Close called on",self.objectName())
        if self.window:
            ix = self.window.tabs.indexOf(self)
            if ix > -1:
                self.window.tabs.removeTab(ix)
                self.deleteLater() # since qt doesn't delete us, we need to explicitly delete ourselves, otherwise the QWidget lives around forever in memory
        self.window, self.plugin, self.wallet, self.wallet_name = (None,) * 4

    #overrides PrintError super
    def diagnostic_name(self): 
        return self.plugin.name + "@" + str(self.wallet_name)
        
        

