# -*- coding: utf-8 -*-

# Form implementation generated from reading ui file 'ui.ui'
#
# Created by: PyQt5 UI code generator 5.11.2
#
# WARNING! All changes made in this file will be lost!

from PyQt5 import QtCore, QtGui, QtWidgets

class Ui_Instance(object):
    def setupUi(self, Instance):
        Instance.setObjectName("Instance")
        Instance.resize(873, 350)
        self.gb_charities = QtWidgets.QGroupBox(Instance)
        self.gb_charities.setGeometry(QtCore.QRect(460, 10, 401, 171))
        self.gb_charities.setObjectName("gb_charities")
        self.tree_charities = QtWidgets.QTreeWidget(self.gb_charities)
        self.tree_charities.setGeometry(QtCore.QRect(10, 30, 381, 101))
        self.tree_charities.setAlternatingRowColors(True)
        self.tree_charities.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.tree_charities.setTextElideMode(QtCore.Qt.ElideMiddle)
        self.tree_charities.setRootIsDecorated(True)
        self.tree_charities.setWordWrap(False)
        self.tree_charities.setHeaderHidden(False)
        self.tree_charities.setColumnCount(3)
        self.tree_charities.setObjectName("tree_charities")
        item_0 = QtWidgets.QTreeWidgetItem(self.tree_charities)
        self.tree_charities.header().setVisible(True)
        self.tree_charities.header().setCascadingSectionResizes(False)
        self.tree_charities.header().setMinimumSectionSize(10)
        self.tree_charities.header().setSortIndicatorShown(True)
        self.tb_plus = QtWidgets.QToolButton(self.gb_charities)
        self.tb_plus.setGeometry(QtCore.QRect(350, 140, 26, 22))
        self.tb_plus.setToolButtonStyle(QtCore.Qt.ToolButtonTextOnly)
        self.tb_plus.setAutoRaise(True)
        self.tb_plus.setObjectName("tb_plus")
        self.tb_minus = QtWidgets.QToolButton(self.gb_charities)
        self.tb_minus.setEnabled(False)
        self.tb_minus.setGeometry(QtCore.QRect(320, 140, 26, 22))
        self.tb_minus.setToolButtonStyle(QtCore.Qt.ToolButtonTextOnly)
        self.tb_minus.setAutoRaise(True)
        self.tb_minus.setObjectName("tb_minus")
        self.lbl_bad_address = QtWidgets.QLabel(self.gb_charities)
        self.lbl_bad_address.setGeometry(QtCore.QRect(10, 140, 281, 16))
        font = QtGui.QFont()
        font.setItalic(True)
        self.lbl_bad_address.setFont(font)
        self.lbl_bad_address.setObjectName("lbl_bad_address")
        self.fr_title = QtWidgets.QFrame(Instance)
        self.fr_title.setGeometry(QtCore.QRect(20, 10, 428, 96))
        self.fr_title.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.fr_title.setFrameShadow(QtWidgets.QFrame.Raised)
        self.fr_title.setLineWidth(1)
        self.fr_title.setObjectName("fr_title")
        self.gridLayout = QtWidgets.QGridLayout(self.fr_title)
        self.gridLayout.setObjectName("gridLayout")
        self.lbl_icon = QtWidgets.QLabel(self.fr_title)
        self.lbl_icon.setText("")
        self.lbl_icon.setPixmap(QtGui.QPixmap(":/DonateSpareChange/resources/icon64.png"))
        self.lbl_icon.setObjectName("lbl_icon")
        self.gridLayout.addWidget(self.lbl_icon, 0, 0, 2, 1)
        self.lbl_title = QtWidgets.QLabel(self.fr_title)
        font = QtGui.QFont()
        font.setPointSize(20)
        self.lbl_title.setFont(font)
        self.lbl_title.setAlignment(QtCore.Qt.AlignLeading|QtCore.Qt.AlignLeft|QtCore.Qt.AlignVCenter)
        self.lbl_title.setObjectName("lbl_title")
        self.gridLayout.addWidget(self.lbl_title, 0, 1, 1, 1)
        self.lbl_byline = QtWidgets.QLabel(self.fr_title)
        font = QtGui.QFont()
        font.setPointSize(13)
        self.lbl_byline.setFont(font)
        self.lbl_byline.setTextFormat(QtCore.Qt.AutoText)
        self.lbl_byline.setAlignment(QtCore.Qt.AlignLeading|QtCore.Qt.AlignLeft|QtCore.Qt.AlignVCenter)
        self.lbl_byline.setOpenExternalLinks(True)
        self.lbl_byline.setObjectName("lbl_byline")
        self.gridLayout.addWidget(self.lbl_byline, 0, 2, 1, 1)
        self.lbl_blurb = QtWidgets.QLabel(self.fr_title)
        self.lbl_blurb.setAlignment(QtCore.Qt.AlignLeading|QtCore.Qt.AlignLeft|QtCore.Qt.AlignVCenter)
        self.lbl_blurb.setWordWrap(True)
        self.lbl_blurb.setObjectName("lbl_blurb")
        self.gridLayout.addWidget(self.lbl_blurb, 1, 1, 1, 2)

        self.retranslateUi(Instance)
        QtCore.QMetaObject.connectSlotsByName(Instance)

    def retranslateUi(self, Instance):
        _translate = QtCore.QCoreApplication.translate
        Instance.setWindowTitle(_translate("Instance", "Form"))
        self.gb_charities.setTitle(_translate("Instance", "Charities / Donation Destinations"))
        self.tree_charities.headerItem().setText(0, _translate("Instance", "Enabled"))
        self.tree_charities.headerItem().setText(1, _translate("Instance", "Donee Name"))
        self.tree_charities.headerItem().setText(2, _translate("Instance", "Donee Address"))
        __sortingEnabled = self.tree_charities.isSortingEnabled()
        self.tree_charities.setSortingEnabled(False)
        self.tree_charities.topLevelItem(0).setText(1, _translate("Instance", "EatBCH"))
        self.tree_charities.topLevelItem(0).setText(2, _translate("Instance", "qqakdjalkdjlsidqwilasldihdadhalskdhadulaskdhaskud"))
        self.tree_charities.setSortingEnabled(__sortingEnabled)
        self.tb_plus.setToolTip(_translate("Instance", "Add a new charity"))
        self.tb_plus.setText(_translate("Instance", "➕"))
        self.tb_minus.setToolTip(_translate("Instance", "Delete selected charities"))
        self.tb_minus.setText(_translate("Instance", "➖"))
        self.lbl_bad_address.setToolTip(_translate("Instance", "One or more addresses are invalid"))
        self.lbl_bad_address.setText(_translate("Instance", "<html><head/><body><p><font color=#BC1E1E><i>One or more addresses are invalid</i></font></p></body></html>"))
        self.lbl_title.setText(_translate("Instance", "Donate Spare Change 1.0"))
        self.lbl_byline.setToolTip(_translate("Instance", "<html><head/><body><p><pre>https://github.com/cculianu/DonateSpareChange</pre></p></body></html>"))
        self.lbl_byline.setText(_translate("Instance", "<html><head/><body><p>by <a href=\"https://github.com/cculianu/DonateSpareChange\">Calin Culianu</a><br/></p></body></html>"))
        self.lbl_blurb.setText(_translate("Instance", "<html><head/><body><p><span style=\" font-size:12pt;\">Automatically donate your spare change to the destinations of your choice.</span></p></body></html>"))

from . import resources
