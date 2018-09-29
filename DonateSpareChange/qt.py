import sys, os, time

from PyQt5.QtGui import *
from PyQt5.QtCore import *
from PyQt5.QtWidgets import *

from electroncash.address import Address
from electroncash.i18n import _
from electroncash.plugins import BasePlugin, hook
from electroncash.util import PrintError
from electroncash_gui.qt.amountedit import BTCAmountEdit
from collections import OrderedDict


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

    @hook
    def set_label(self, wallet, name, text):
        for instance in self.instances:
            if instance.wallet == wallet:
                instance.on_set_label(name, text)

class Instance(QWidget, PrintError):
    ''' Encapsulates a wallet-specific instance. '''

    sig_network_updated = pyqtSignal()
    sig_user_tabbed_to_us = pyqtSignal()

    def __init__(self, plugin, wallet, window):
        super().__init__()
        self.plugin = plugin
        self.wallet = wallet
        self.window = window
        self.wallet_name = os.path.split(wallet.storage.path)[1]
        self.setObjectName(self.diagnostic_name())
        self.data = self.DataModel(self, self.wallet.storage, self.plugin.config)
        self.already_warned_watching = False
        self.disabled = False

        # do stuff to setup UI...
        from .ui import Ui_Instance
        self.ui = Ui_Instance()
        self.ui.setupUi(self)

        self.ch_mgr = self.CharitiesMgr(self, self.ui, self.data)
        self.cr_mgr = self.CriteriaMgr(self, self.ui, self.data)
        self.co_mgr = self.CoinsMgr(self, self.ui, self.data)
        self.engine = self.Engine(self, self.data)

        # connect any signals/slots
        self.cr_mgr.criteria_changed_signal.connect(self.co_mgr.refresh)
        self.sig_user_tabbed_to_us.connect(self.on_user_tabbed_to_us)
        # connect cashaddr signal to refresh all UI addresses, etc
        self.window.cashaddr_toggled_signal.connect(self.refresh_all)

        if self.wallet.network:
            self.wallet.network.register_callback(self.on_network_updated, ['updated'])

        # finally, add the UI to the wallet window
        window.tabs.addTab(self, plugin.icon(), plugin.shortName())

    def on_network_updated(self, event, *args):
        # network thread
        if event == 'updated':
            self.sig_network_updated.emit() # this passes the call to the gui thread

    def on_user_tabbed_to_us(self):
        warn_user = False
        try:
            if self.wallet.is_watching_only() and not self.already_warned_watching:
                self.already_warned_watching = True
                warn_user = True
        except AttributeError: # Exception happens because I don't think all wallets have the is_watching_only method
            pass
        if warn_user:
            self.window.show_critical(msg=_("{}\n\nThe {} plugin requires a spending wallet in order to function.").format(_("This is a watching-only wallet."), self.plugin.shortName()),
                                      title=_("This is a watching-only wallet."),
                                      parent=self.window)
            self.disabled = True
            gbs = [self.ui.gb_criteria, self.ui.gb_coins, self.ui.gb_charities]
            for gb in gbs: gb.setEnabled(False) # disable all controls

    def on_set_label(self, name, text):
        # TODO: Make this catch tx's that the user sends from send tab or transaction dialog and inform the Engine
        self.print_error("set_label:",name,"=",text)

    def event(self, event):
        ''' overrides QObject: a hack used to detect when the prefs screen was closed or when our tab comes to foreground. '''
        #self.print_error("got event with type",event.type())
        if event.type() in (QEvent.WindowUnblocked, QEvent.ShowToParent) and self.wallet:
            if event.type() == QEvent.ShowToParent:
                self.sig_user_tabbed_to_us.emit()
            # if window unblocked, maybe user changed prefs. inform our managers to refresh() as maybe base_unit changed, etc.
            self.refresh_all()

        return super().event(event) # Make real QWidget implementation actually handle the event

    def refresh_all(self):
        self.ch_mgr.refresh()
        self.cr_mgr.refresh()
        self.co_mgr.refresh()

    def wallet_has_password(self):
        try:
            return self.wallet.has_password() or not self.wallet.check_password(None)
        except AttributeError: # happens on watching-only wallets which don't have the requiside methods
            return False

    class CharitiesMgr(QObject, PrintError):
        ''' Manages the 'Charities' treewidget and associated GUI controls and per-wallet data. '''

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

            # Context Menu Setup
            self.ui.tree_charities.setContextMenuPolicy(Qt.CustomContextMenu)
            self.ui.tree_charities.customContextMenuRequested.connect(self.on_context_menu)

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
                #self.print_error("Got chk from", chk, "=",b, "name=", name)
                self.save()
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
            self.save()

        def on_minus(self):
            items = self.ui.tree_charities.selectedItems()
            if items:
                msg = _("Do you really wish to delete these {} items?").format(len(items)) if len(items) > 1 else _("Do you really wish to delete this item?")
                if self.parent.window.question(msg=msg, title=_("Confirm Delete")):
                    root = self.ui.tree_charities.invisibleRootItem()
                    for item in items:
                        root.removeChild(item) # item will get gc'd by Python
                    self.save()
            self.check_ok()

        def on_plus(self):
            i = self.ui.tree_charities.topLevelItemCount() + 1
            self.append_item((False, "Charity #%d"%i, "Charity Address %d"%i))

        def save(self):
            items = self.ui.tree_charities.findItems("", Qt.MatchContains, 0)
            charities = []
            for item in items:
                chk = self.ui.tree_charities.itemWidget(item, 0)
                name, address = item.text(1), item.text(2)
                #self.print_error("saving ", name, address)
                enabled = False
                if chk: enabled = bool(chk.isChecked()) # sometimes the checkbox is missing when the user just added a new item, and we get the signal too quickly
                charities.append((enabled, name, address))

            self.data.set_charities(charities, save=True)

        def refresh(self):
            # this doesn't need to be refreshed. ignore...
            pass

        def on_context_menu(self, point):
            if self.ui.tree_charities.selectedItems():
                menu = QMenu(self.ui.tree_charities)
                menu.addAction(_("Delete"), self.on_minus)
                menu.exec_(self.ui.tree_charities.viewport().mapToGlobal(point))



    class CriteriaMgr(QObject, PrintError):
        ''' Manages the 'Criteria' groupbox and associated GUI controls and per-wallet data. '''

        criteria_changed_signal = pyqtSignal()

        WARN_HIGH_AMOUNT = 200000 # in sats: 2 mBCH

        def __init__(self, parent, ui, data):
            super().__init__(parent)
            self.parent = parent # Instance
            self.ui = ui
            self.data = data
            self.last_warned = time.time()-10.0

            # Do some UI setup....
            # We couldn't put the BTCAmountEdit in the Qt .ui file because it's a custom python class, so we
            # create it here programatically as a child of the dummy fr_amount stub widget we had in the UI.
            self.ui.amount_edit = BTCAmountEdit(decimal_point = self.parent.window.get_decimal_point,
                                                is_int = False,
                                                parent = self.ui.fr_amount)
            self.ui.amount_edit.setFixedWidth(16777215) # this constant removes fixed width constraint set up by AmountEdit class
            layout = QGridLayout(self.ui.fr_amount)
            layout.addWidget(self.ui.amount_edit, 0, 0)
            layout.setContentsMargins(0,0,0,0)
            self.ui.fr_amount.setFrameStyle(0) # the frame was there so I could see the widget in Qt Designer. Remove it. :)
            self.ui.fr_amount.setLineWidth(0)

            self.reload()

            # Connect signals/slots
            self.ui.amount_edit.textChanged.connect(self.on_amount_changed)
            self.ui.sb_age.valueChanged.connect(self.on_age_changed)
            self.ui.chk_autodonate.clicked.connect(self.on_auto_checked)

        def diagnostic_name(self): # from PrintError
            return self.__class__.__name__ + "@" + self.parent.diagnostic_name()

        def refresh(self):
            #self.print_error("refresh")
            self.reload()

        def reload(self):
            cd = self.data.get_changedef()
            is_auto = self.data.get_autodonate() and not self.parent.wallet_has_password()
            self.ui.chk_autodonate.setChecked(is_auto)
            threshSats, minage, agetype = cd
            self.ui.amount_edit.setAmount(threshSats)
            self.ui.sb_age.setValue(minage)
            if isinstance(agetype, int) and agetype >= 0 and agetype < self.ui.cb_age.count():
                self.ui.cb_age.setCurrentIndex(agetype)

        def on_amount_changed(self):
            sats = self.ui.amount_edit.get_amount()
            if sats is not None:
                #self.print_error("sats",sats)
                cd = self.data.get_changedef()
                if sats >= self.WARN_HIGH_AMOUNT and self.data.get_global_warn_high_thresh() and time.time()-self.last_warned > 10.0:
                    # Custom logic to warn the user if they specify an amount above self.WARN_HIGH_AMOUNT
                    self.ui.amount_edit.blockSignals(True)
                    reply = custom_question_box(msg = (_("You specified a spare change threshold that is rather high (above {}).").format(self.parent.window.format_amount_and_units(self.WARN_HIGH_AMOUNT))
                                                       + "\n\n" +
                                                       _("Are you sure you wish to proceed?")),
                                                title = _("Are you sure?"),
                                                parent = self.parent.window,
                                                buttons = OrderedDict([ (_("Yes && Never ask again!") , QMessageBox.YesRole),
                                                                        (_("No") , QMessageBox.NoRole),
                                                                        (_("Yes") , QMessageBox.YesRole), ]))
                    self.ui.amount_edit.blockSignals(False)
                    self.last_warned = time.time()
                    #self.print_error("reply",reply)
                    if reply == _("No"):
                        self.ui.amount_edit.setAmount(cd[0]) # revert back
                        return # and abort
                    else:
                        if reply != _("Yes"):
                            # they wish to proceed.. and never be asked again!
                            self.data.set_global_warn_high_thresh(False)
                        # the below ends up calling us again with the same value. We do this to make sure the GUI and us are in synch (can get out of synch due to blocked signals above)
                        # Note: the above check won't be invoked again immediately though, because the last_warned timeout won't have expired.
                        self.ui.amount_edit.setAmount(sats)
                        return

                self.data.set_changedef((sats, *cd[1:]), save=True)
                self.criteria_changed_signal.emit()

        def on_age_changed(self, age):
            cd = self.data.get_changedef()
            self.data.set_changedef((cd[0], age, *cd[2:]), save=True)
            self.criteria_changed_signal.emit()

        def on_auto_checked(self, b):
            if self.parent.wallet_has_password():
                self.ui.chk_autodonate.setChecked(False)
                self.parent.window.show_warning(msg=_("Auto-donation requires that you disable all password protection on this wallet.\n\n" +
                                                       "If you wish to proceed, use the pasword 'lock' tool button to clear the password\n" +
                                                       " for this wallet, then try again."),
                                                 title = _("Password-Free Wallet Required"),
                                                 parent = self.parent.window)

    class CoinsMgr(QObject, PrintError):
        ''' Manages the 'Coins' treewidget and associated GUI controls and per-wallet data. '''

        def __init__(self, parent, ui, data):
            super().__init__(parent)
            self.parent = parent # Instance
            self.ui = ui
            self.data = data

            self.ui.tree_coins.setColumnWidth(0, 120)
            self.ui.tree_coins.setColumnWidth(1, 120)
            self.ui.tree_coins.setColumnWidth(2, 70)
            self.brushNormal, self.brushIneligible, self.brushFrozen, self.brushEligible = QBrush(), QBrush(QColor("#999999")), QBrush(QColor("lightblue")), QBrush(QColor("darkgreen"))
            self.ui.cb_age.setHidden(True) # not used for now

            self.reload()

            self.parent.sig_network_updated.connect(self.refresh) # when tx's come in or blocks come in, we need to refresh utxo list.
            self.ui.tree_coins.itemSelectionChanged.connect(self.on_selection_changed) # coins selection changed
            self.ui.bt_donate_selected.clicked.connect(self.on_donate_selected)
            self.ui.bt_donate_all.clicked.connect(self.on_donate_all)
            # Context Menu Setup
            self.ui.tree_coins.setContextMenuPolicy(Qt.CustomContextMenu)
            self.ui.tree_coins.customContextMenuRequested.connect(self.on_context_menu)

        def diagnostic_name(self): # from PrintError
            return self.__class__.__name__ + "@" + self.parent.diagnostic_name()

        def on_close(self):
            if self.parent.wallet.network:
                self.parent.wallet.network.unregister_callback(self.on_updated)

        def refresh(self):
            #self.print_error("refresh")
            self.reload()

        def get_coins(self, eligible_only = False, from_treewidget = False, selected_only = False):
            ''' Returns a list of coins, either from the cached items in the treewidget or from the wallet. '''

            if from_treewidget:
                if selected_only:
                    items = self.ui.tree_coins.selectedItems()
                else:
                    items = self.ui.tree_coins.findItems("", Qt.MatchContains, 0)
                okcoins = 0
                def chk(item):
                    nonlocal okcoins
                    ok = item.data(0, Qt.UserRole)['is_eligible']
                    okcoins = okcoins + int(ok)
                    return not eligible_only or ok
                coins = [item.data(0, Qt.UserRole) for item in items if chk(item)] # narrow down to eligibile coins if eligible_only is true
                return coins, okcoins
            else:
                okcoins = 0
                amount, age, agetype = self.data.get_changedef()
                if amount is None: amount = 0
                lh = self.parent.wallet.get_local_height()
                coins = self.parent.wallet.get_utxos(domain = None, exclude_frozen = False, mature = True, confirmed_only = False)
                for c in coins:
                    c['is_frozen'] = int(bool(self.parent.wallet.is_frozen(c['address'])))
                    c['age'] = (lh - c['height']) + 1 if c['height'] and c['height'] > 0 else -1
                    valtest = c['value'] <  amount
                    agetest = age <= 0 or ( c['age'] >= age )
                    #self.print_error("lh",lh,"cheight",c['height'],"age",age)
                    c['is_eligible'] = int(not c['is_frozen'] and valtest and agetest)
                    if c['is_eligible']:
                        c['eligibility_text'] = _("Eligible for donation")
                        okcoins += 1
                    else:
                        txt = _("Ineligible:") + " "
                        reasons = []
                        if c['is_frozen']: reasons.append(_("Frozen"))
                        else:
                            if not valtest: reasons.append(_("Amount"))
                            if not agetest: reasons.append(_("Age"))
                        c['eligibility_text'] = txt + ', '.join(reasons)
                coins.sort(key=lambda c: [ c['is_frozen'], 100-c['is_eligible'], c['value'], c['height'], ], reverse = False)
                if eligible_only:
                    return [c for c in coins if c['is_eligible'] ], okcoins
                return coins, okcoins

        def reload(self):
            #self.print_error("reload")
            if not self.parent.wallet: return
            scroll_pos_val = self.ui.tree_coins.verticalScrollBar().value() # save previous scroll bar position
            oldSelCoins, oldCount = self.get_coins(from_treewidget = True, selected_only = True) # save previous selection
            oldSelNames = {self.get_name(selCoin) for selCoin in oldSelCoins}

            self.ui.tree_coins.clear()
            self.ui.bt_donate_selected.setEnabled(False)

            coins, okcoins = self.get_coins()
            for c in coins:
                item = self.add_item(c)
                if self.get_name(c) in oldSelNames:
                    # restore previous selection state on coin
                    item.setSelected(True)

            if not len(coins):
                self.ui.lbl_utxos.setText(_("This wallet is empty and has no coins"))
            else:
                self.ui.lbl_utxos.setText(_("{}/{} coins meet the specified criteria").format(okcoins, len(coins)))
            self.ui.bt_donate_all.setEnabled(okcoins)

            timer = QTimer(self) # attach a timer object to us. Timer will be auto-killed either by python GC or if we die before it fires because we are its parent
            def restoreScrollBar():
                nonlocal timer
                timer.deleteLater() # otherwise dead timer lives on.
                timer = None
                if self.ui and self.ui.tree_coins:
                    self.ui.tree_coins.updateGeometry()
                    self.ui.tree_coins.verticalScrollBar().setValue(scroll_pos_val) # restore scroll bar to previous

            timer.setSingleShot(True)
            timer.timeout.connect(restoreScrollBar)
            timer.start(1)  # need to do this from a timer some time later due to Qt quirks

        def add_item(self, c):
            address, value, height, is_frozen, is_eligible, status = c.get('address').to_ui_string(), c.get('value'), c.get('height'), c.get('is_frozen'), c.get('is_eligible'), c.get('eligibility_text')
            amtText = self.parent.window.format_amount(value) + ' '+ self.parent.window.base_unit()
            ageText = (str(c.get('age')) + " blks") if c.get('age') > -1 else _("unconf.")
            item = QTreeWidgetItem(self.ui.tree_coins, [amtText, address, ageText, status])
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            item.setData(0, Qt.UserRole, c) # save the coin itself inside the item.. in case we need it later
            brush = self.brushNormal
            if is_frozen: brush = self.brushFrozen
            elif not is_eligible: brush = self.brushIneligible
            nCols = self.ui.tree_coins.columnCount()
            if brush != self.brushNormal:
                for i in range(0, nCols):
                    item.setForeground(i, brush)
            if is_eligible: item.setForeground(nCols-1, self.brushEligible)
            return item

        def get_name(self, coin):
            return self.parent.window.utxo_list.get_name(coin)

        def on_selection_changed(self):
            coins, has_eligible = self.get_coins(from_treewidget = True, eligible_only = True, selected_only = True)
            self.ui.bt_donate_selected.setEnabled(has_eligible)

        def on_context_menu(self, point):
            coins, has_eligible = self.get_coins(from_treewidget = True, eligible_only = False, selected_only = True)
            if coins:
                menu = QMenu(self.ui.tree_coins)
                menu.addAction(_("Show in Coins Tab"), lambda: self.on_show_in_coins_tab(coins))
                if has_eligible:
                    menu.addAction(_("Donate Selected"), self.on_donate_selected)
                menu.exec_(self.ui.tree_coins.viewport().mapToGlobal(point))

        def on_show_in_coins_tab(self, coins):
            names = {self.get_name(coin) for coin in coins}
            utxo_list = self.parent.window.utxo_list
            utxo_list.clearSelection()
            items = utxo_list.findItems("", Qt.MatchContains, 0)
            for item in items:
                if item.data(0, Qt.UserRole) in names:
                    item.setSelected(True)
            tab = self.parent.window.utxo_tab
            visible = self.parent.window.config.get('show_{}_tab'.format(tab.tab_name), False)
            if not visible:
                self.parent.window.toggle_tab(tab)
            self.parent.window.tabs.setCurrentWidget(tab)

        def on_donate_selected(self):
            coins, okcount = self.get_coins(from_treewidget = True, eligible_only = True, selected_only = True)
            if coins:
                self.print_error("on_donate_selected",*[self.get_name(coin) for coin in coins])

        def on_donate_all(self):
            coins, okcount = self.get_coins(from_treewidget = True, eligible_only = True, selected_only = False)
            if coins:
                self.print_error("on_donate_all", *[self.get_name(coin) for coin in coins])


    # nested class.. handles writing our data dict to/from persisten store
    class DataModel:
        ''' Interface to the permanent store for this plugin's persistent data & settings (basically, Wallet Storage) '''

        def __init__(self, parent, storage, config):
            self.parent = parent
            self.storage = storage
            self.config = config
            self.keys = {
                'root' : self.parent.plugin.name + "__Data__v00", # the root-level key that goes into wallet storage for all of our plugin data
                'charities' : 'charities', # the addresses, which ends up being a list of tuples (enabled, name, address_str)
                'change_def' : 'change_def', # the definition of what constitutes change, which is a simple tuple
                'autodonate' : 'autodonate', # if true, automatically donate change without prompting. requires unenecrypted wallet
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
                change_def = (10500, 100, 0)
                d['charities'] = charities
                d['change_def'] = change_def
                d['initted'] = True
            return d

        def put_data(self, datadict, save=False):
            self.storage.put(self.keys['root'], datadict)
            if save: self.save()

        def save(self):
            self.storage.write()

        def get_charities(self, valid_enabled_only = False):
            d = self.get_data()
            ret = d.get('charities', list())
            if valid_enabled_only:
                ret = [r for r in ret if r[0] and Address.is_valid(r[2])]
            return ret

        def set_charities(self, charities, save=False):
            if isinstance(charities, list):
                d = self.get_data()
                d['charities'] = charities
                self.put_data(d, save=save)

        def get_changedef(self):
            d = self.get_data()
            return d.get('change_def')

        def set_changedef(self, cd, save=False):
            if isinstance(cd, (tuple, list)) and len(cd) >= 3:
                d = self.get_data()
                d['change_def'] = cd
                self.put_data(d, save=save)

        def get_autodonate(self):
            return self.get_data().get('autodonate', False)

        def set_autodonate(self, b, save = False):
            try:
                b = bool(b)
                d = self.get_data()
                d['autodonate'] = b
                self.put_data(d, save=save)
            except ValueError:
                pass

        def get_global_warn_high_thresh(self):
            return self.config.get(self.parent.plugin.name + '__WarnHighAmountThresh', True)

        def set_global_warn_high_thresh(self, b):
            self.config.set_key(self.parent.plugin.name + '__WarnHighAmountThresh', bool(b))

    class Engine(QObject, PrintError):
        ''' The donation engine.  Encapsulates all logic of picking coins to donate, prompting user, setting up Send tab, etc '''
        def __init__(self, parent, data):
            super().__init__(parent) # QObject c'tor
            self.parent = parent # class 'Instance' instance
            self.data = data

        def diagnostic_name(self): # from PrintError
            return self.__class__.__name__ + "@" + self.parent.diagnostic_name()

    # Uncomment to test object lifetime and make sure Qt is deleting us.
    #def __del__(self):
    #    print("**** __del__ ****")

    # called by self.plugin on wallet close - deallocate all resources and die.
    def close(self):
        self.print_error("Close called on",self.objectName())
        if self.wallet.network:
            self.wallet.network.unregister_callback(self.on_network_updated)
        if self.window:
            ix = self.window.tabs.indexOf(self)
            if ix > -1:
                self.window.tabs.removeTab(ix)
                self.deleteLater() # since qt doesn't delete us, we need to explicitly delete ourselves, otherwise the QWidget lives around forever in memory
        self.disabled = True
        self.window, self.plugin, self.wallet, self.wallet_name, self.data, self.ch_mgr, self.co_mgr, self.cr_mgr, self.engine = (None,) * 9 # trigger object cleanup sooner rather than later!

    #overrides PrintError super
    def diagnostic_name(self):
        return self.plugin.name + "@" + str(self.wallet_name)


def custom_question_box(msg, title="", buttons=[_("Cancel"), _("Ok")], parent = None):
    mb = QMessageBox(QMessageBox.Question, title, msg, QMessageBox.NoButton, parent)
    if not buttons: buttons = [_("Ok")] # make sure we have at least 1 button!
    if isinstance(buttons, dict):
        for but,role in buttons.items():
            mb.addButton(but, role)
    else:
        for i,but in enumerate(buttons):
            mb.addButton(but, QMessageBox.AcceptRole if i > 0 else QMessageBox.RejectRole)
    mb.exec()
    clicked = mb.clickedButton()
    return clicked.text()


class RoundRobin(list):
    ''' A list that is useful for a round-robin queue, allowing you to take items in the list and put them to the back.
        Note that .to_back() allows you to send arbitrary items in the list to the back, not just the first item.
        .update() allows one to update the list whilst preserving the original order for items that remain in the list.
    '''

    def front(self):
        if len(self):
            return self[0]
        return None

    def push_front_unique(self, item):
        ''' Only inserts item if it doesn't already exist in the list and is not None. '''
        if item is not None and item not in self:
            self.insert(0, item)
        return self

    def update(self, l):
        ''' Update this list to include only items in the collection l, deleting items from self that aren't in l, whilst preserving
            the original order of self. As a final pass it inserts to front all items in l that weren't originally in self.'''
        tmp = self.copy()
        self.clear()
        for t in tmp:
            if t in l:
                self.append(t)
        for item in l:
            self.push_front_unique(item)
        return self

    def to_back(self, item = None):
        if item is None:
            # this call path basically says to unconditionally take whatever was at the front and put it to the back.
            item = self[0] # IndexError possible here if caller misuing class
            self.pop(0)
            self.append(item)
        else:
            for i, elem in enumerate(self):
                # look for item in list.. if found, take it out
                if elem == item:
                    self.pop(i)
                    break
            # and now put item at back. note this may end up growing the list by 1 if item was not in list.  but that's ok and is a feature.
            self.append(item)
        return self
