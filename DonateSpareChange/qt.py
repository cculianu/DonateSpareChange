##!/usr/bin/env python3
#
# DonateSpareChange; an auto-donation plugin for Electron Cash version 3.3+
# Author: Calin Culianu <calin.culianu@gmail.com>
# Copyright (C) 2019 Calin Culianu
# LICENSE: MIT
#
import sys, os, time, binascii, math

from PyQt5.QtGui import *
from PyQt5.QtCore import *
from PyQt5.QtWidgets import *

from electroncash.address import Address
from electroncash.bitcoin import TYPE_ADDRESS
from electroncash.i18n import _
from electroncash.plugins import BasePlugin, hook
from electroncash.util import PrintError, profiler, NotEnoughFunds, ExcessiveFee, InvalidPassword
from electroncash_gui.qt.amountedit import BTCAmountEdit
from electroncash_gui.qt.util import ColorScheme
from electroncash import version
from collections import OrderedDict, namedtuple


class Plugin(BasePlugin):

    HAS_SCHNORR_API = None

    def __init__(self, parent, config, name):
        super().__init__(parent, config, name)
        self.instances = list() # list of 'Instance' objects
        self.gui = None # pointer to Electrum.gui singleton
        self.config = config
        self.is_new_network_callback_api = False
        self.is_slp = False
        self.is_shufbeta = False
        self._check_version()  # will set is_new_network_callback_api & is_slp

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
        if Plugin.HAS_SCHNORR_API is None:
            Plugin.HAS_SCHNORR_API = bool(getattr(window, 'is_schnorr_enabled', False) or getattr(window.wallet, 'is_schnorr_enabled', False))
            self.print_error("Schnorr API present in this Electron Cash:", "YES" if Plugin.HAS_SCHNORR_API else "No")
        self.instances.append(Instance(self, wallet, window))

    @hook
    def close_wallet(self, wallet):
        for instance in self.instances:
            if instance.wallet == wallet:
                iname = instance.diagnostic_name()
                instance.close()
                self.instances.remove(instance) # pop it from the list of instances, python gc will remove it
                self.print_error("removed instance:", iname)
                return

    @hook
    def set_label(self, wallet, name, text):
        for instance in self.instances:
            if instance.wallet == wallet:
                instance.on_set_label(name, text)

    def _check_version(self):
        full_ver = CopiedCode.parse_package_version(version.PACKAGE_VERSION)
        normalized_ver = full_ver[:-1]
        variant = full_ver[-1]

        if variant == "ShufBeta":
            self.is_shufbeta = True
        elif variant != '':
            self.print_error("Unknown Electron Cash variant:", variant)
            return
        elif normalized_ver >= (3,4) and normalized_ver < (3,5):
            self.is_slp = True

        if self.is_shufbeta:
            min_new_api_ver = (3,9,8)
        elif self.is_slp:
            min_new_api_ver = (3,4,6)
        else:
            min_new_api_ver = (3,3,7)

        self.is_new_network_callback_api = normalized_ver >= min_new_api_ver


class Instance(QWidget, PrintError):
    ''' Encapsulates a wallet-specific instance. '''

    sig_network_updated = pyqtSignal()
    sig_user_tabbed_to_us = pyqtSignal()
    sig_user_tabbed_from_us = pyqtSignal()
    sig_window_moved = pyqtSignal()
    sig_window_resized = pyqtSignal()
    sig_window_activation_changed = pyqtSignal()
    sig_window_unblocked = pyqtSignal()

    def __init__(self, plugin, wallet, window):
        super().__init__()
        self.plugin = plugin
        self.wallet = wallet
        self.window = window
        self.window.installEventFilter(self)
        self.wallet_name = os.path.split(wallet.storage.path)[1]
        self.data = self.DataModel(self, self.wallet.storage, self.plugin.config)
        self.already_warned_incompatible = False
        self.incompatible, self.is_slp = self.is_wallet_incompatibile()
        self.disabled = False
        self.did_register_callback = False

        # do stuff to setup UI...
        from .ui import Ui_Instance
        self.ui = Ui_Instance()
        self.ui.setupUi(self)
        self.platform_cleanups()

        self.ch_mgr = self.CharitiesMgr(self, self.ui, self.data)
        self.cr_mgr = self.CriteriaMgr(self, self.ui, self.data)
        self.co_mgr = self.CoinsMgr(self, self.ui, self.data)
        self.engine = self.Engine(self, self.wallet, self.window, self.co_mgr, self.data)

        # connect any signals/slots
        self.cr_mgr.criteria_changed_signal.connect(self.co_mgr.refresh)
        self.sig_user_tabbed_to_us.connect(self.on_user_tabbed_to_us)
        # connect cashaddr signal to refresh all UI addresses, etc
        self.window.cashaddr_toggled_signal.connect(self.refresh_all)
        self.sig_window_unblocked.connect(self.ch_mgr.refresh) # special case -- prefs screen may have closed and our units changed.

        self.disable_if_incompatible()

        if self.wallet.network and not self.incompatible:
            if self.plugin.is_new_network_callback_api:
                interests = ['wallet_updated', 'blockchain_updated', 'verified2']
            else:
                self.print_error("Warning: Your version of Electron Cash is deprecated. Please upgrade.")
                interests = ['updated', 'verified']
            self.wallet.network.register_callback(self.on_network, interests)
            self.did_register_callback = True


        # finally, add the UI to the wallet window
        window.tabs.addTab(self, plugin.icon(), plugin.shortName())

        if not self.incompatible:
            self.engine.start()

    def platform_cleanups(self):
        if sys.platform != 'darwin':
            if sys.platform == 'linux':
                stuff2adjust = [ self.ui.lbl_title, self.ui.lbl_byline, self.ui.lbl_blurb, self.ui.tree_charities, self.ui.bt_donate_selected, self.ui.bt_donate_all ]
                for w in stuff2adjust:
                    f = w.font()
                    defaultFont = QApplication.instance().font()
                    defaultFont.setPointSize(int(round(f.pointSize()*0.85)))
                    w.setFont(defaultFont)
            else: # windows, etc
                stuff2adjust = [ self.ui.lbl_title, self.ui.lbl_byline, self.ui.lbl_blurb, self.ui.tree_coins ]
                defaultFont = QApplication.instance().font()
                def adjust(w):
                    f = w.font()
                    f.setFamily(defaultFont.family())
                    w.setFont(f)
                    childs = w.children()
                    for child in childs:
                        if isinstance(child, QWidget):
                            adjust(child)
                adjust(self)
                for w in stuff2adjust:
                    f = w.font()
                    f.setPointSize(int(round(f.pointSize()*0.85)))
                    w.setFont(f)

    def on_network(self, event, *args):
        # network thread
        if event == 'updated' and (not args or args[0] is self.wallet):
            self.sig_network_updated.emit() # this passes the call to the gui thread
        elif event == 'verified': # grr.. old api sucks
            self.sig_network_updated.emit() # this passes the call to the gui thread
        elif event in ('wallet_updated', 'verified2') and args[0] is self.wallet:
            self.sig_network_updated.emit() # this passes the call to the gui thread
        elif event == 'blockchain_updated':
            self.sig_network_updated.emit() # this passes the call to the gui thread

    def is_wallet_incompatibile(self):
        is_watching_only_method = getattr(self.wallet, 'is_watching_only', lambda: False)
        is_slp = self.wallet.storage.get('wallet_type', '').strip().lower() == 'bip39-slp'
        try:
            from electroncash.keystore import Hardware_KeyStore
            from electroncash.wallet import Multisig_Wallet
            if (is_slp
                or is_watching_only_method()
                or isinstance(self.wallet, (Multisig_Wallet,))
                or any([isinstance(k, Hardware_KeyStore) for k in self.wallet.get_keystores()])):
                # wallet is multisig, hardware, slp, or watching only.. return True (incompatible)
                return True, is_slp
            else:
                return False, False
        except (ImportError, AttributeError) as e:
            # Hmm. Electron Cash API change? Proceed anyway and the user will just get error messages if plugin can't spend.
            self.print_error("Error checking wallet compatibility:",repr(e))
        return is_watching_only_method() or is_slp, is_slp

    def on_user_tabbed_to_us(self):
        #self.print_error("user tabbed to us")
        warn_user = False
        try:
            if self.incompatible and not self.already_warned_incompatible:
                self.already_warned_incompatible = True
                warn_user = True
        except AttributeError: # Exception happens because I don't think all wallets have the is_watching_only method
            pass

        if warn_user:
            def warning_popup(self):
                if self.is_slp:
                    msg = _("This is an incompatible wallet type.") + "\n\n" + _("SLP token wallets are not supported, as a safety feature.")
                else:
                    msg = _("This is an incompatible wallet type.") + "\n\n" + _("The {} plugin only supports imported private key or standard spending wallets.").format(self.plugin.shortName())
                self.window.show_critical(msg=msg,
                                          title=_("{} - Incompatible Wallet").format(self.plugin.shortName()),
                                          parent=self.window)
            do_later(self, 10, warning_popup, self)  # allow the event loop to run to paint this widget, then show the popup in 10 ms

    def disable_if_incompatible(self):
        if self.incompatible:
            self.disabled = True
            self.print_error("Wallet is incompatible, disabling for this wallet")
            gbs = [self.ui.gb_criteria, self.ui.gb_coins, self.ui.gb_charities]
            for gb in gbs: gb.setEnabled(False) # disable all controls

    def on_set_label(self, name, text):
        self.engine.on_set_label(name, text)

    def event(self, event):
        ''' overrides QObject: a hack used to detect when the prefs screen was closed or when our tab comes to foreground. '''
        #self.print_error("got event with type",event.type())
        if event.type() in (QEvent.WindowUnblocked, QEvent.ShowToParent) and self.wallet:
            if event.type() == QEvent.ShowToParent:
                self.sig_user_tabbed_to_us.emit()
            else:
                self.sig_window_unblocked.emit()
            # if window unblocked, maybe user changed prefs. inform our managers to refresh() as maybe base_unit changed, etc.
            self.refresh_all()
        elif event.type() in (QEvent.HideToParent,):
            # user left our UI. Tell interested code about this (mainly the PopupLabel cares)
            self.sig_user_tabbed_from_us.emit()

        return super().event(event) # Make real QWidget implementation actually handle the event

    def eventFilter(self, window, event):
        ''' Spies on events to parent window to figure out when the user moved or resized the window, and announces that fact via signals. '''
        #self.print_error("eventFilter got event", event.type())
        if window == self.window:
            if event.type() == QEvent.Move:
                self.sig_window_moved.emit()
            elif event.type() == QEvent.Resize:
                self.sig_window_resized.emit()
            elif event.type() == QEvent.ActivationChange:
                self.sig_window_activation_changed.emit()
        return super().eventFilter(window, event)

    def refresh_all(self):
        self.cr_mgr.refresh()
        self.co_mgr.refresh()
        # NB: we do NOT call ch_mgr.refresh() here because this refresh_all function is called a on_network and the user might be editing
        # a charity at the time.
        #
        # instead, we explicitly call ch_mgr.refresh() in key places where we think it needs refreshing.

    def wallet_has_password(self):
        try:
            return self.wallet.has_password()
        except AttributeError: # happens on watching-only wallets which don't have the requiside methods
            return False

    # Uncomment to test object lifetime and make sure Qt is deleting us.
    #def __del__(self):
    #    print("**** __del__ ****")

    # called by self.plugin on wallet close - deallocate all resources and die.
    def close(self):
        self.print_error("Close called on an Instance")
        self.engine.stop()
        if self.did_register_callback:
            self.wallet.network and self.wallet.network.unregister_callback(self.on_network)
        if self.window:
            self.window.removeEventFilter(self)
            ix = self.window.tabs.indexOf(self)
            if ix > -1:
                self.window.tabs.removeTab(ix)
                self.deleteLater() # since qt doesn't delete us, we need to explicitly delete ourselves, otherwise the QWidget lives around forever in memory
        self.disabled = True
        self.window, self.plugin, self.wallet, self.wallet_name, self.data, self.ch_mgr, self.co_mgr, self.cr_mgr, self.engine = (None,) * 9 # trigger object cleanup sooner rather than later!

    #overrides PrintError super
    def diagnostic_name(self):
        return self.plugin.name + "@" + str(self.wallet_name)


    class CharitiesMgr(QObject, PrintError):
        ''' Manages the 'Charities' treewidget and associated GUI controls and per-wallet data. '''

        def __init__(self, parent, ui, data):
            super().__init__(parent)
            self.parent = parent
            self.ui = ui
            self.data = data
            self.ui.tree_charities.setColumnWidth(0, 60)
            self.ui.tree_charities.setSortingEnabled(True)
            self.refresh_blocked = False
            self.myred = "#BC1E1E" if not ColorScheme.dark_scheme else ColorScheme.RED.as_color().name()

            self.reload()

            # setup connections
            self.ui.tree_charities.itemSelectionChanged.connect(self.on_selection_changed) # charities selection changed
            self.ui.tree_charities.itemChanged.connect(self.on_item_changed) # charities item edited
            self.ui.tb_minus.clicked.connect(self.on_minus)
            self.ui.tb_plus.clicked.connect(self.on_plus)

            # Context Menu Setup
            self.ui.tree_charities.setContextMenuPolicy(Qt.CustomContextMenu)
            self.ui.tree_charities.customContextMenuRequested.connect(self.on_context_menu)

            # Mogrify color -- fixup for dark scheme looking weird and ColorScheme class failing us with red not looking ok.
            bad_address_text = '''
            <html><head/><body><p><font color="{}"><i>{}</i></font></p></body></html>
            '''.format(self.myred, _("One or more addresses are invalid"))
            self.ui.lbl_bad_address.setText(bad_address_text)

        def diagnostic_name(self): # from PrintError
            return self.__class__.__name__ + "@" + self.parent.diagnostic_name()


        def append_item(self, char_entry):
            en, name, address = char_entry
            total = self.parent.window.format_amount(self.data.history_get_total_for_address(address), whitespaces=True)
            #import random # for testing layout
            #total = self.parent.window.format_amount(random.randint(1000,10000000), whitespaces=True)
            item = QTreeWidgetItem(self.ui.tree_charities, ["", total, name, address])
            pointSize = 12 if sys.platform == 'darwin' else 10
            #if len(total.strip()) > 12:
            #    pointSize -= 1
            item.setFont(1, QFont("Fixed", pointSize))
            item.setFlags(item.flags() | Qt.ItemIsEditable)
            chk = QCheckBox()
            self.ui.tree_charities.setItemWidget(item, 0, chk)
            i = self.ui.tree_charities.topLevelItemCount()-1
            item.setData(0, Qt.UserRole, i)
            item.setData(1, Qt.UserRole, total) # remember original text in case user "edits" it.
            if en:
                chk.setChecked(True)
            def on_chkd(b,chk=chk,name=name):
                #self.print_error("Got chk from", chk, "=",b, "name=", name)
                self.save()
            chk.toggled.connect(on_chkd)

        def reload(self):
            self.ui.tree_charities.clear()
            hitem = self.ui.tree_charities.headerItem()
            hitem.setText(1, _("Donated ({})").format(self.parent.window.base_unit())) # label the header with the correct amount
            hitem.setTextAlignment(0, Qt.AlignCenter)
            hitem.setTextAlignment(1, Qt.AlignJustify)
            chars = self.data.get_charities()

            for char in chars:
                self.append_item(char)

            self.check_ok()

        def check_ok(self, item_changed = None):
            items = self.ui.tree_charities.findItems("", Qt.MatchContains, 0)
            allValid = True
            badBrush, goodBrush = QBrush(QColor(self.myred)), QBrush(ColorScheme.DEFAULT.as_color())
            for i,item in enumerate(items):
                name, address = (item.text(2), item.text(3))
                #self.print_error("item ", i, "name=", name, "address=", address)
                if Address.is_valid(address):
                    item.setForeground(3, goodBrush)
                else:
                    item.setForeground(3, badBrush)
                    allValid = False
                    if item == item_changed:
                        item_changed.setSelected(False) # force it unselected so they see the error of their ways!
            self.ui.lbl_bad_address.setHidden(allValid)


        def on_selection_changed(self):
            self.ui.tb_minus.setEnabled(len(self.ui.tree_charities.selectedItems()))

        def on_item_changed(self, item, column):
            if column == 0: return
            if column == 1: item.setText(1, item.data(1, Qt.UserRole)); return # suppress editing of amounts column and just restore its previous value
            if column == 3:
                address = item.text(3)
                if address.lower().strip().startswith("bitcoincash:"):
                    # strip out bitcoincash: part as it just wastes screen space.
                    tmp = address.split(":")
                    if len(tmp) == 2:
                        address = ':'.join(tmp[1:])
                        item.setText(3, address)
            self.check_ok(item)
            self.save()

        def on_minus(self):
            self.refresh_blocked = True
            try:
                items = self.ui.tree_charities.selectedItems()
                if items:
                    msg = _("Do you really wish to delete these {} items?").format(len(items)) if len(items) > 1 else _("Do you really wish to delete this item?")
                    if self.parent.window.question(msg=msg, title=_("Confirm Delete")):
                        root = self.ui.tree_charities.invisibleRootItem()
                        for item in items:
                            root.removeChild(item) # item will get gc'd by Python
                        self.save()
                self.check_ok()
            finally:
                self.refresh_blocked = False

        def on_plus(self):
            i = self.ui.tree_charities.topLevelItemCount() + 1
            self.append_item((False, "Charity #%d"%i, "Charity Address %d"%i))

        def save(self):
            items = self.ui.tree_charities.findItems("", Qt.MatchContains, 0)
            charities = []
            for item in items:
                chk = self.ui.tree_charities.itemWidget(item, 0)
                name, address = item.text(2), item.text(3)
                #self.print_error("saving ", name, address)
                enabled = False
                if chk: enabled = bool(chk.isChecked()) # sometimes the checkbox is missing when the user just added a new item, and we get the signal too quickly
                charities.append((enabled, name, address))

            self.data.set_charities(charities, save=True)

        def refresh(self):
            if not self.refresh_blocked:
                self.reload()

        def on_context_menu(self, point):
            if self.ui.tree_charities.selectedItems():
                menu = QMenu(self.ui.tree_charities)
                menu.addAction(_("Delete"), self.on_minus)
                menu.exec_(self.ui.tree_charities.viewport().mapToGlobal(point))



    class CriteriaMgr(QObject, PrintError):
        ''' Manages the 'Criteria' groupbox and associated GUI controls and per-wallet data. '''

        criteria_changed_signal = pyqtSignal()
        user_began_editing_signal = pyqtSignal()
        autodonate_disabled_signal = pyqtSignal()

        WARN_HIGH_AMOUNT = 200000 # in sats: 2 mBCH

        def __init__(self, parent, ui, data):
            super().__init__(parent)
            self.parent = parent # Instance
            self.ui = ui
            self.data = data
            self.last_warned = time.time()-10.0
            self.popup_label = None
            self.popup_timer = None

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

            # NB: Connect these first -- user_began_editing is fired unconditionally on edit. Will be user to indicate to user why we turned off autopay
            self.ui.amount_edit.textChanged.connect(self.user_began_editing_signal)
            self.ui.sb_age.valueChanged.connect(self.user_began_editing_signal)
            self.user_began_editing_signal.connect(self.on_user_began_editing)

            self.ui.amount_edit.textChanged.connect(self.on_amount_changed)
            self.ui.sb_age.valueChanged.connect(self.on_age_changed)
            self.ui.chk_autodonate.clicked.connect(self.on_auto_checked)
            self.ui.chk_1tx.clicked.connect(self.on_singletx_checked)

            self.parent.sig_user_tabbed_from_us.connect(self.cleanup_popup_label)
            self.parent.sig_window_moved.connect(self.cleanup_popup_label)
            self.parent.sig_window_resized.connect(self.cleanup_popup_label)
            self.parent.sig_window_activation_changed.connect(self.cleanup_popup_label)

        def diagnostic_name(self): # from PrintError
            return self.__class__.__name__ + "@" + self.parent.diagnostic_name()

        def refresh(self):
            #self.print_error("refresh")
            self.reload()

        def reload(self):
            cd = self.data.get_changedef()
            is_auto = self.data.get_autodonate() and not self.parent.wallet_has_password()
            if not is_auto and self.data.get_autodonate():
                self.on_auto_checked(False) # force the setting off
            else:
                self.ui.chk_autodonate.setChecked(is_auto)
            self.ui.chk_1tx.setChecked(self.data.get_singletx())
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
                if sats >= self.WARN_HIGH_AMOUNT and self.data.get_warn_high_thresh() and time.time()-self.last_warned > 10.0:
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
                            self.data.set_warn_high_thresh(False)
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
            was = self.data.get_autodonate()
            if b:
                self.cleanup_popup_label()
                if self.parent.wallet_has_password():
                    self.parent.window.show_warning(msg=_("Auto-donation requires that you disable all password protection on this wallet.\n\n" +
                                                           "If you wish to proceed, use the pasword 'lock' tool button to clear the password\n" +
                                                           " for this wallet, then try again."),
                                                     title = _("Password-Free Wallet Required"),
                                                     parent = self.parent.window)
                    b = False
                else:
                    cd = self.data.get_changedef()
                    if not self.parent.window.question(title = _("Confirm Auto-Donation"),
                                                       parent = self.parent.window,
                                                       msg = (_("Before auto-donation is enabled, please confirm:") + "\n\n" +
                                                              _("Automatically donate coins valued less than: {}.").format(self.parent.window.format_amount_and_units(cd[0])) + "\n\n" +
                                                              _("With age of at least: {} confirmed blocks.").format(cd[1]) + "\n\n" +
                                                              _("Do you wish to proceed?") ) ):
                        b = False
            self.ui.chk_autodonate.setChecked(b)
            self.data.set_autodonate(b, save = True)
            if was and not b:
                self.autodonate_disabled_signal.emit()

        def on_singletx_checked(self, b):
            self.data.set_singletx(b, save = True)

        def on_user_began_editing(self):
            self.print_error("User began editing, disabling auto-pay")
            if self.ui.chk_autodonate.isChecked():
                self.on_auto_checked(False) # forces checkbox off
                from .popup_widget import PopupLabel

                class MyPopupLabel(PopupLabel):
                    def mousePressEvent(self, e):
                        if self.cmgr: self.cmgr.cleanup_popup_label()
                        return super().mousePressEvent(e)
                if self.popup_label:
                    self.cleanup_popup_label()
                self.popup_label = MyPopupLabel('<font color="#ffffff"><p>{}</p></font>'.format(_("You began editing, so we turned off auto-donation."))
                                                + '<font color="#ddffee"><p><b>{}</b></p></font>'.format(_("You may turn it back on when done.")),
                                                self.ui.chk_autodonate)
                self.popup_label.cmgr = self
                self.popup_label.finalOpacity = 0.95
                self.popup_label.resize(self.popup_label.width(), 120)
                self.popup_label.setPointerPosition(PopupLabel.RightSide)
                self.popup_label.showRelativeTo(self.ui.chk_autodonate)
                self.popup_timer = do_later(self.ui.chk_autodonate, 10000.0, self.cleanup_popup_label)

        def cleanup_popup_label(self):
            if self.popup_label:
                if self.popup_label.isVisible():
                    self.popup_label.hide()
                self.popup_label.deleteLater()
                self.popup_label.cmgr = None
                self.popup_label = None
            if self.popup_timer:
                self.popup_timer.stop()
                self.popup_timer.deleteLater()
                self.popup_timer = None

    class CoinsMgr(QObject, PrintError):
        ''' Manages the 'Coins' treewidget and associated GUI controls and per-wallet data. '''

        def __init__(self, parent, ui, data):
            super().__init__(parent)
            self.parent = parent # Instance
            self.ui = ui
            self.data = data
            self.active = False # we won't refresh on "updated" signals until this is true (when user tabs to us)

            self.ui.tree_coins.setColumnWidth(0, 120)
            self.ui.tree_coins.setColumnWidth(1, 120)
            self.ui.tree_coins.setColumnWidth(2, 70)
            self.brushNormal, self.brushIneligible, self.brushFrozen, self.brushEligible = (
                QBrush(), QBrush(QColor("#999999")),
                QBrush(QColor("lightblue") if ColorScheme.dark_scheme else QColor("#003399")),
                QBrush(ColorScheme.GREEN.as_color() if ColorScheme.dark_scheme else QColor("darkgreen"))
            )
            self.ui.cb_age.setHidden(True) # not used for now
            if sys.platform != 'darwin':
                self.ui.tree_coins.setFont(QFont('Helvetica', 10))

            self.reload()

            self.parent.sig_user_tabbed_from_us.connect(lambda: self.on_activate_status_change(False))
            self.parent.sig_user_tabbed_to_us.connect(lambda: self.on_activate_status_change(True))
            self.parent.sig_network_updated.connect(self.on_network_updated) # when tx's come in or blocks come in, we need to refresh utxo list.
            self.ui.tree_coins.itemSelectionChanged.connect(self.on_selection_changed) # coins selection changed
            self.ui.bt_donate_selected.clicked.connect(self.on_donate_selected)
            self.ui.bt_donate_all.clicked.connect(self.on_donate_all)
            # Context Menu Setup
            self.ui.tree_coins.setContextMenuPolicy(Qt.CustomContextMenu)
            self.ui.tree_coins.customContextMenuRequested.connect(self.on_context_menu)

        def diagnostic_name(self): # from PrintError
            return self.__class__.__name__ + "@" + self.parent.diagnostic_name()

        def on_network_updated(self):
            if self.active: self.refresh()

        def on_activate_status_change(self, b):
            ''' The active status flag gets set by intercepting when we become the active tab. When we are inactive we suppress auto-refresh
            of the coins tab on network 'updated' signals as a performance boost.  This is ok to do because when the user tabs to us,
            parent Instance class forces a full UI refresh anyway. '''
            self.active = b
            #self.print_error("Active status set to:","ACTIVE" if b else "INACTIVE")

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
                    c['is_frozen'] = int(bool(self.parent.wallet.is_frozen(c['address'])) or c.get('is_frozen_coin', False))
                    c['age'] = (lh - c['height']) + 1 if c['height'] and c['height'] > 0 else -1
                    valtest = c['value'] <  amount
                    agetest = age <= 0 or ( c['age'] >= age )
                    dusttest = c['value'] > 770 # we hard-code 546 + 224 as the minimal size we consider "dust"
                    #self.print_error("lh",lh,"cheight",c['height'],"age",age)
                    c['is_eligible'] = int(not c['is_frozen'] and valtest and agetest and dusttest)
                    if c['is_eligible']:
                        c['eligibility_text'] = _("Eligible for donation")
                        okcoins += 1
                    else:
                        txt = _("Ineligible:") + " "
                        reasons = []
                        if c['is_frozen']: reasons.append(_("Frozen"))
                        else:
                            if not dusttest: reasons.append(_("Dust"))
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
            self.ui.tree_coins.clear()
            if not self.parent.wallet or self.parent.incompatible:
                return
            scroll_pos_val = self.ui.tree_coins.verticalScrollBar().value() # save previous scroll bar position
            oldSelCoins, oldCount = self.get_coins(from_treewidget = True, selected_only = True) # save previous selection
            oldSelNames = {self.get_name(selCoin) for selCoin in oldSelCoins}

            self.ui.bt_donate_selected.setEnabled(False)

            coins, okcoins = self.get_coins()
            for c in coins:
                item = self.add_item(c)
                if self.get_name(c) in oldSelNames:
                    # restore previous selection state on coin
                    item.setSelected(True)

            if not len(coins):
                self.ui.lbl_utxos.setText(_("This wallet is currently empty and has no coins"))
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
            age = c.get('age')
            ageText = (str(age) + " blk" + ("s" if age > 1 else "")) if age > -1 else _("unconf.")
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
            self._do_manual_donate(coins)

        def _do_manual_donate(self, coins):
            if coins:
                is_batched = self.data.get_singletx()
                if not is_batched and len(coins) > 1:
                    if not self.parent.window.question(_("You are about to create {} separate transaction windows. You will need to sign and broadcast each one.\n\nProceed?").format(len(coins))):
                        return
                if not self.parent.engine.manual_donate(coins, batched=is_batched):
                    self.parent.window.show_error(_("No charities are enabled!"))

        def on_donate_all(self):
            coins, okcount = self.get_coins(from_treewidget = True, eligible_only = True, selected_only = False)
            self._do_manual_donate(coins)


    # nested class.. handles writing our data dict to/from persisten store
    class DataModel:
        ''' Interface to the permanent store for this plugin's persistent data & settings (basically, Wallet Storage) '''

        HistoryEntry = namedtuple('HistoryEntry', 'address name amount ref txout') # address=str, name=str, amount=int, ref=str, txout=str

        def __init__(self, parent, storage, config):
            self.parent = parent
            self.storage = storage
            self.config = config
            self.keys = {
                'root' : self.parent.plugin.name + "__Data__v00", # the root-level key that goes into wallet storage for all of our plugin data
                'charities' : 'charities', # the addresses, which ends up being a list of tuples (enabled, name, address_str)
                'change_def' : 'change_def', # the definition of what constitutes change, which is a simple tuple
                'autodonate' : 'autodonate', # if true, automatically donate change without prompting. requires unenecrypted wallet
                'roundrobin' : 'roundrobin', # list of active charities in round-robin fashion. leftmost entry is the next one to receive a donation
                'singletx' : 'singletx', # iff true, donations are made with 1 big tx covering all coins, hindering privacy but saving on fees
                'history' : 'history', # a dict of address -> list of HistoryEntry entries
                'warn_hi' : 'warn_hi', # if true, warn user when inputting change threshold above 2 mBCH (default: True)
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
                    (False, "CashShuffle", "qqqxxmjyavdkwdj6npa5w6xl0fzq3wc5furaqdpl59"),
                    (False, "Electron-Cash", "qz4wq9m860zr5p2nfdpttm5ymdqdyt3psc95qjagae"),
                    (False, "bchd", "qrhea03074073ff3zv9whh0nggxc7k03ssh8jv9mkx"),
                    (False, "CrescentCash", "qptnypuugy29lttleggl7l0vpls0vg295q9nsavw6g"),
                    (False, "FloweeTheHub", "qpgn5ka4jptc98a9ftycvujxx33e79nxuqlz5mvxns"),
                    (False, "Bitcoin-ABC", "qqeht8vnwag20yv8dvtcrd4ujx09fwxwsqqqw93w88"),
                    (False, "Chaintip", "qpznjz9qd0fl5fe9sfrkuy8rznt8qw066yvkgsezy5"),
                    (False, "Gitcash", "qrdf9w034w9l7lgu7yt2tem7403paeky2geytpuccn"),
                    (False, "CashAddress", "qp4atx0z6h6atuzchuaqssnkdqag95ecdqtt5nx8z8"),
                ]
                change_def = (10500, 72, 0) # sats, blocks, age_type(not used yet)
                d['charities'] = charities
                d['change_def'] = change_def
                d['autodonate'] = False
                d['roundrobin'] = list()
                d['singletx'] = False
                d['history'] = dict()
                d['warn_hi'] = True
                d['initted'] = True
            return d

        def put_data(self, datadict, save=True):
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

        def set_charities(self, charities, save=True):
            if isinstance(charities, list):
                d = self.get_data()
                d['charities'] = charities
                self.put_data(d, save=save)

        def get_changedef(self):
            d = self.get_data()
            return d.get('change_def')

        def set_changedef(self, cd, save=True):
            if isinstance(cd, (tuple, list)) and len(cd) >= 3:
                d = self.get_data()
                d['change_def'] = cd
                self.put_data(d, save=save)

        def get_autodonate(self):
            return self.get_data().get('autodonate', False)

        def set_autodonate(self, b, save = True):
            try:
                b = bool(b)
                d = self.get_data()
                d['autodonate'] = b
                self.put_data(d, save=save)
            except ValueError:
                pass

        def get_roundrobin(self):
            return RoundRobin(self.get_data().get('roundrobin', list()))

        def set_roundrobin(self, rr, save = True):
            if not isinstance(rr, (list, tuple, RoundRobin, set)):
                raise ValueError('set_roundrobin requires a list, tuple, set, or RoundRobin argument')
            d = self.get_data()
            d['roundrobin'] = list(rr)
            self.put_data(d, save=save)

        def get_history(self):
            return self.get_data().get('history', dict())

        def set_history(self, h, save = True):
            if not isinstance(h, dict):
                raise ValueError('set_history requires a dictionary argument')
            d = self.get_data()
            d['history'] = h
            self.put_data(d, save = save)

        def history_put_entry(self, hentry, save = True):
            if not isinstance(hentry, self.HistoryEntry):
                raise ValueError('history_put requires a HistoryEntry argument')
            h = self.get_history()
            l = h.get(hentry.address, list())
            wasempty = not bool(l)
            if hentry not in l:
                l.append(hentry)
            if wasempty: h[hentry.address] = l
            self.set_history(h, save = save)

        def history_get_for_address(self, address):
            l = self.get_history().get(address, list())
            ret = list()
            for item in l:
                hentry = self.HistoryEntry(*item)
                ret.append(hentry)
            return ret

        def history_get_total_for_address(self, address):
            l = self.history_get_for_address(address)
            return sum([hentry.amount for hentry in l])

        def get_singletx(self):
            return self.get_data().get('singletx', False)

        def set_singletx(self, b, save = True):
            try:
                b = bool(b)
                d = self.get_data()
                d['singletx'] = b
                self.put_data(d, save=save)
            except ValueError:
                pass

        def get_warn_high_thresh(self):
            return self.get_data().get('warn_hi', True)

        def set_warn_high_thresh(self, b, save = True):
            try:
                b = bool(b)
                d = self.get_data()
                d['warn_hi'] = b
                self.put_data(d, save=save)
            except ValueError:
                pass

    class Engine(QObject, PrintError):
        ''' The donation engine.  Encapsulates all logic of picking coins to donate, prompting user, setting up Send tab, etc '''

        timer_interval = 10 * 1e3 # value is Qt ms value -- 10 second interval

        def __init__(self, parent, wallet, window, co_mgr, data):
            super().__init__(parent) # QObject c'tor
            self.parent = parent # class 'Instance' instance
            self.wallet = wallet
            self.window = window
            if Plugin.HAS_SCHNORR_API:
                if getattr(window, 'is_schnorr_enabled', None): # 4.0.3 & 4.0.4 API
                    self._is_schnorr_enabled_func = window.is_schnorr_enabled
                elif getattr(window.wallet, 'is_schnorr_enabled', None): # 4.0.4-git and beyond API
                    self._is_schnorr_enabled_func = window.wallet.is_schnorr_enabled
                else:
                    raise RuntimeError("Cannot find 'is_schnorr_enabled' function -- FIXME")
            else:
                self._is_schnorr_enabled_func = lambda: False
            self.data = data
            self.co_mgr = co_mgr
            self.parent.cr_mgr.autodonate_disabled_signal.connect(self.on_autodonate_disabled)
            self.rr = self.data.get_roundrobin()
            self.timer = QTimer(self)
            self.timer.setInterval(self.timer_interval) # wake up every 10 seconds
            self.timer.timeout.connect(self.do_check)
            self.is_foregrounded = False
            self.last_notify_set = set()
            self.pending_tx_histories = dict() # dict of tx_desc -> list of HistoryEntry
            self.suppress_auto = 0

            self.update_rr()

            self.parent.sig_user_tabbed_to_us.connect(lambda: self.set_foregrounded(True))
            self.parent.sig_user_tabbed_from_us.connect(lambda: self.set_foregrounded(False))

        def diagnostic_name(self): # from PrintError
            return self.__class__.__name__ + "@" + self.parent.diagnostic_name()

        def on_set_label(self, name, text):
            ''' this will be used to catch tx's that have completed / been sent in non-auto-donate mode by embedding a cookie in tx desc '''
            self.print_error("set_label called with ", name, text)
            hentries = self.pending_tx_histories.pop(text, None)
            if hentries:
                for hentry in hentries:
                    txout = hentry[-1]
                    if txout.find(':') < 0:
                        # was missing txid because this was generated by manual_donate where tx was unsigned
                        txout = name + ":" + txout
                        hentry = self.data.HistoryEntry(*hentry[:-1], txout)
                    self.data.history_put_entry(hentry, save=False)
                self.data.save()
                self.parent.ch_mgr.refresh() # force history update

        def set_foregrounded(self, b): self.is_foregrounded = b

        def update_rr(self):
            charities = self.data.get_charities(valid_enabled_only = True)
            charities = [ tuple(charity[1:]) for charity in charities ] # get rid of the "enabled" column -- our round-robin list consits of name,address tuples
            self.rr.update(charities) #.update preserves original order for ones that are kept.
            return bool(self.rr)

        def do_check(self):
            if self.parent.disabled or self.parent.incompatible:
                return
            if not self.wallet.network or not self.wallet.network.is_connected() or not self.wallet.network.is_up_to_date() or not self.wallet.is_up_to_date():
                self.print_error("Network not connected or wallet/network not up-to-date, will try again later...")
                return
            coins, ct = self.co_mgr.get_coins(from_treewidget = False, eligible_only = True)
            if coins and self.update_rr():
                if self.data.get_autodonate() and not self.wallet.has_password(): # pw check here again in case it changed in the meantime
                    if not self.suppress_auto:
                        self.auto_donate(coins)
                    else:
                        self.print_error("Auto-donate suppressed due to extant donations-related txdialog")
                else:
                    self.notify_user(coins)

        def newref(self): return str(binascii.hexlify(os.urandom(8))).split("'")[1]

        def manual_donate(self, coins, batched=True):
            ''' This will either make 1 big batched TX or pop up many tx windows '''
            if not self.update_rr() or not coins:
                return 0
            list_of_coins = []
            if batched:
                list_of_coins = [coins]
            else:
                list_of_coins = [[c] for c in coins]
            for coins in list_of_coins:
                tx, desc, ref, donees = self.make_transaction(coins)
                if not tx:
                    self.show_error(_("There was a problem creating the transaction. Please contact the developer."))
                    return -1
                i = 0
                for donee,amt in donees.items():
                    name,address = donee
                    # address name amount ref txout
                    hentry = self.data.HistoryEntry(address,name,amt,ref,str(i))
                    l = self.pending_tx_histories.get(desc,list())
                    l.append(hentry)
                    self.pending_tx_histories[desc] = l
                    i += 1

                # .. aaaand Show it!
                self.window.show_transaction(tx, desc)

                if self.data.get_autodonate():
                    ''' Hack -- in case the user hit "donate eligible" while in auto-mode, suppress auto-donation while
                        the tx dialog is up using this monkey-patching technique. ;) '''

                    try:
                        from electroncash_gui.qt.transaction_dialog import dialogs
                        txdlg = dialogs[-1]
                        origMethod = txdlg.closeEvent
                        def myCloseEvent(event):
                            if not self.parent or not self.parent.plugin:
                                origMethod(event)
                                return # early return -- plugin was closed!
                            self.print_error("monkey-patched tx dialog close called", event)
                            origMethod(event)
                            if event.isAccepted() and self.suppress_auto:
                                self.suppress_auto -= 1
                                self.print_error("tx dialog close suppress_auto =", self.suppress_auto)
                        txdlg.closeEvent = myCloseEvent
                        self.suppress_auto += 1
                    except (AttributeError, ImportError):
                        import traceback
                        traceback.print_exc()
                        self.print_error("Could not suppress auto")

            return 1

        def on_autodonate_disabled(self):
            self.suppress_auto = 0 # turn off 'auto' suppression because user messed with UI


        def auto_donate(self, coins):
            self.print_error("Auto-donate called with ", coins)
            def on_box_is_up():
                if not self.parent or not self.parent.plugin:
                    return # early return -- auto kicked off just as the window was closing. abort!
                txs = []
                try:
                    if self.data.get_singletx():
                        tx, desc, ref, donees = self.make_transaction(coins)
                        self.wallet.sign_transaction(tx, None)
                        txs.append((tx, desc, ref, donees))
                    else:
                        for c in coins:
                            tx, desc, ref, donees = self.make_transaction([c])
                            self.wallet.sign_transaction(tx, None)
                            txs.append((tx, desc, ref, donees))
                except InvalidPassword:
                    self.data.set_autodonate(False)
                    self.parent.cr_mgr.refresh()
                    self.show_error(_("Wallet now has a password. Auto-donate was turned off."))
                    return

                bcast = None
                network = self.wallet.network
                if hasattr(network, 'broadcast_transaction'):
                    bcast = network.broadcast_transaction
                elif hasattr(network, 'broadcast'):
                    bcast = network.broadcast
                else:
                    # wtf. someone changed the API
                    self.show_error(_("Don't know how to broadcast a transaction. Are you on Electron Cash 3.2 or above?"))
                    return
                ct = 0
                tot = 0
                for tx,desc,ref,donees in txs:
                    if tx is None:
                        self.print_error("WARNING: tx is None for", desc)
                        continue
                    status, data = bcast(tx)
                    if status:
                        if data != tx.txid(): self.print_error("Warning: txid != data", data, tx.txid())
                        self.wallet.set_label(tx.txid(), desc)
                        i = 0
                        for donee,amt in donees.items():
                            name,address = donee
                            # address name amount ref txout
                            self.data.history_put_entry(self.data.HistoryEntry(address,name,amt,ref,tx.txid()+":"+str(i)), save=False)
                            i += 1
                            ct += 1
                            tot += amt
                    else:
                        self.print_error("WARNING: got false status for", desc,tx.txid())
                if ct:
                    self.data.save()
                    self.window.notify(_("Auto-donated {} coins, {}").format(ct,self.window.format_amount_and_units(int(tot))))
                    self.parent.ch_mgr.refresh() # so that we see the new history immediately


            show_please_wait(msg=_("Auto-Donating, please wait..."), title=self.parent.plugin.shortName(),
                             parent=None, on_shown=on_box_is_up)

        def make_transaction(self, coins):
            totalSats = 0
            ref = self.newref()
            desc = self.parent.plugin.shortName() + ": "
            donees = dict()
            outputs = list()
            for coin in coins:
                donee = self.rr.rotate()
                amt = donees.get(donee, 0)
                sats = coin['value']
                amt += sats
                totalSats += sats
                donees[donee] = amt
            for donee,amt in donees.items():
                addr_str = donee[1]
                address = Address.from_string(addr_str)
                outputs.append((TYPE_ADDRESS, address, int(amt)))
            desc += ', '.join([donee[0] for donee in donees])
            desc += " (ref: %s)" % ref

            tx = None
            try:
                schnorr_kwargs={}
                if Plugin.HAS_SCHNORR_API:
                    schnorr_kwargs['sign_schnorr'] = self._is_schnorr_enabled_func()
                # first make a 0-fee tx to figure out the tx size.
                tx0 = self.wallet.make_unsigned_transaction(inputs=coins, outputs=outputs, config=self.window.config, fixed_fee=0, **schnorr_kwargs)
                size = tx0.estimated_size()
                # next, make each output pay a portion of the fee to reach 1.0 sats/B
                each_fee = int(math.ceil(size / len(outputs)))
                #print("got size",size,"each_fee",each_fee)
                #print("old outputs",outputs)
                outputs = [ (o[0], o[1], o[2]-each_fee) for o in outputs ]
                donees = { d:v-each_fee for d,v in donees.items() }
                #print("revised outputs",outputs)
                if any([ bool(o[2] <= 0) for o in outputs]):
                    raise NotEnoughFunds
                tx = self.wallet.make_unsigned_transaction(inputs=coins, outputs=outputs, config=self.window.config, fixed_fee=each_fee*len(outputs), **schnorr_kwargs)
            except NotEnoughFunds:
                self.show_error(_("Insufficient funds"))
            except ExcessiveFee:
                self.show_error(_("Excessive Fee"))
            except BaseException as e:
                import traceback
                traceback.print_exc()
                self.print_error("Outputs:",outputs)
                self.show_error(str(e) or "Unknown Error")

            self.data.set_roundrobin(self.rr)
            return tx, desc, ref, donees

        def show_error(self, msg):
            self.window.show_error(msg = (self.parent.plugin.shortName() + ":\n\n" + msg))

        def notify_user(self, coins):
            #self.print_error("Prompt user called with", coins)
            if not coins: return
            if self.is_foregrounded:
                # We don't do anything when the user has the tab open, because they can do
                # manual donations then, so they don't need to be prompted.
                #self.print_error("Not notifying user, tab is foregrounded.")
                return
            '''
            if (self.window.tabs.currentWidget() == self.window.send_tab
                and self.window.message_e.text().startswith(self.parent.plugin.shortName() + ":")
                and self.window.message_e.isReadOnly()):
                # todo: only suppress here if the active send tab thing is our tx?
                #self.print_error("Not notifying user, send tab is already active.")
                return
            '''
            coinset = { self.co_mgr.get_name(c) for c in coins }
            if coinset == self.last_notify_set:
                #self.print_error("Not notifying user, set of coins hasn't changed.")
                return
            msg = [
                _("You have {} coins eligible for donation totaling {}.").format(len(coins),
                                                                                 self.window.format_amount_and_units(sum([c['value'] for c in coins])) ),
                "",
                #_("Do you wish to go to the Send tab and donate now?")
                _("(Go to the 'Donate Change' tab to donate)")
            ]
            self.window.notify(msg[0]) #'\n'.join(msg))
            self.last_notify_set = coinset

        def do_send_tab_send(self, coins):
            self.print_error("Do send tab send called with", coins)

        def stop(self):
            self.timer.stop()

        def start(self):
            self.timer.start()

class RoundRobin(list):
    ''' A list that is useful for a round-robin queue, allowing you to take items in the list and put them to the back.
        Note that .to_back() allows you to send arbitrary items in the list to the back, not just the first item.
        .update() allows one to update the list whilst preserving the original order for items that remain in the list. '''

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
            the original order of self. As a final pass it inserts to front all items in l that weren't originally in self. '''
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
            item = self.pop(0) # IndexError possible here if caller misuing class
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

    def rotate(self): ret = self.front(); self.to_back(); return ret


def custom_question_box(msg, title="", buttons=[_("Cancel"), _("Ok")], parent = None, icon = QMessageBox.Question):

    mb = QMessageBox(icon, title, msg, QMessageBox.NoButton, parent)
    if not buttons: [_("Ok")] # make sure we have at least 1 button!
    if isinstance(buttons, dict):
        for but,role in buttons.items():
            mb.addButton(but, role)
    else:
        for i,but in enumerate(buttons):
            mb.addButton(but, QMessageBox.AcceptRole if i > 0 else QMessageBox.RejectRole)
    mb.setWindowModality(Qt.WindowModal if parent else Qt.ApplicationModal)
    mb.exec_()
    clicked = mb.clickedButton()
    return clicked.text() if clicked else ""

def show_please_wait(msg, title=_("Please wait"), parent = None, on_shown = None):
    from electroncash_gui.qt.util import WindowModalDialog

    class MyDlg(WindowModalDialog):
        sig_shown = pyqtSignal(object)
        def showEvent(self, event):
            ret = super().showEvent(event)
            do_later(self, 20, lambda: self.sig_shown.emit(self))
            #self.sig_shown.emit(self)
            return ret

    dlg = MyDlg(parent=parent, title = title)
    if callable(on_shown):
        dlg.sig_shown.connect(on_shown)
    dlg.sig_shown.connect(lambda x: x.accept()) # force to close if we get to this point
    vbox = QVBoxLayout(dlg)
    vbox.addWidget(QLabel(msg))
    dlg.setWindowModality(Qt.WindowModal if parent else Qt.ApplicationModal)

    dlg.exec_()
    dlg.deleteLater()

def do_later(parent, when_ms, fun, *args):
    timer = QTimer(parent)
    def timer_cb():
        nonlocal timer
        timer.stop()
        timer.deleteLater()
        timer = None
        fun(*args)
    timer.setSingleShot(True)
    timer.timeout.connect(timer_cb)
    timer.start(when_ms)
    return timer

#####
import re
class CopiedCode:
    ''' Code copied from elsewhere (EC sourcecode, etc), that we can't rely
    on always being there across EC versions.. so we pasted it here. The
    nature of plugins! '''

    _RX_NORMALIZER = re.compile(r'(\.0+)*$')
    _RX_VARIANT_TOKEN_PARSE = re.compile(r'^(\d+)(.+)$')

    @staticmethod
    def normalize_version(v):
        """Used for PROTOCOL_VERSION normalization, e.g '1.4.0' -> (1,4) """
        return tuple(int(x) for x in __class__._RX_NORMALIZER.sub('', v.strip()).split("."))

    @staticmethod
    def parse_package_version(pvstr):
        """ Basically returns a tuple of the normalized version plus the 'variant'
        string at the end. Eg '3.3.0' -> (3, 3, ''), '3.2.2CS' -> (3, 2, 2, 'CS'),
        etc.

        Some more examples:
                '3.3.5CS' -> (3, 3, 5, 'CS')
                '3.4.5_iOS' -> (3, 4, 5, '_iOS')
                '3.3.5' -> (3, 3, 5, '')
                '3.3' -> (3, 3, '')
                '3.3.0' -> (3, 3, '')
                '   3.2.2.0 ILikeSpaces ' -> (3, 2, 2, 'ILikeSpaces')
        Note how 0 fields at the end of the version get normalized with the 0 lopped off:
                '3.3.0' -> (3, 3, '')
                '3.5.0.0.0' -> (3, 5, '')
                '3.5.0.0.0_iOS' -> (3, 5, '_iOS')
        ... and, finally: The last element is *always* going to be present as
        a string, the 'variant'. The 'variant' will be the empty string '' if
        this is the default Electron Cash. If you don't like this heterogeneity of
        types in a tuple, take the retVal[:-1] slice of the array to toss it
        (or just use normalize_version above).
        """
        def raise_(e=None):
            exc = ValueError('Failed to parse package version for: "{}"'.format(pvstr))
            if e: raise exc from e
            else: raise exc
        toks = [x.strip() for x in pvstr.split(".")]
        if not toks:
            raise_()
        if toks[-1].isdigit():
            # Missing 'variant' at end.. add the default '' variant.
            toks.append('')
        else:
            # had 'variant' at end, parse it.
            m = __class__._RX_VARIANT_TOKEN_PARSE.match(toks[-1])
            if m:
                # pop off end and...
                toks[-1:] = [m.group(1), # add the digit portion back (note it's still a str at this point)
                             m.group(2).strip()] # add the leftovers as the actual variant
            else:
                raise_()
        try:
            # make sure everything but the last element is an int.
            toks[:-1] = [int(x) for x in toks[:-1]]
        except ValueError as e:
            raise_(e)
        # .. and.. finally: Normalize it! (lopping off zeros at the end)
        toks[:-1] = __class__.normalize_version('.'.join(str(t) for t in toks[:-1]))
        return tuple(toks)
