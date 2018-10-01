![ScreenShot](ScreenShot.png)

# Donate Spare Change - Electron Cash Plugin 

![Icon](resources/icon64.png)

A plugin for Electron Cash that allows you to donate spare 'change' unspent outputs ('Coins' in Electron Cash parlance) automatically, after a certain age and below a certain amount, to charity.  This has the added benefit of preventing change outputs from being recombined with your addreses thus preserving your privacy.  


This is licensed under the MIT open source license.

## Write The Developer 🧐 ##

If you wish to contace me -- my email address is:

  calin DOT culianu "at" gmail.com

## Support The Developer 😃 ##

If you wish to encourage further development (or even just show your appreciation) please feel free to donate to:

  bitcoincash:qphax4s4n9h60jxj2fkrjs35w2tvgd4wzvf52cgtzc
    
![Donate](donate.png)

## Installation ##

1. Download the [latest release](https://github.com/cculianu/DonateSpareChange/releases).
2. Get the latest version of the Electron Cash (either release or code from github -- make sure it has the Plugin Manager that allows addition of plugins).
3. Either select `add plugin` or drag the zip file onto the plugin manager window.
4. It will be installed, and enabled.

## Security Warning ##

I, Calin Culianu (cculianu) author of this plugin, affirm that there is no malicious code intentionally added to this plugin.  If you obtain this plugin from any source other than this github repository, proceed at your own risk!

The reason this needs to be said, is that an enabled Electron Cash plugin has almost complete access and potential control over any wallets that are open.

## Usage ##

Once you have the plugin installed and enabled, you may use it.

1. Select the `Donate Change` tab.
2. Specify a list of recipients.
3. Specify what "change" means to you: an amount and an age for coins defines which coins are considered for donation.
4. You can elect to either auto-donate as coins become eligible, or manually donate. Auto mode requires a non-password protected wallet. Manual mode notifies you as coins become available and you can then manually donate them from within the `Donate Change` tab.

## Known Issues ##

* No real suport for multi-signature wallets (yet! Sorry!).
* No testing and likely no support for hardware wallets (sorry again!).
* If any of the above issues are an issue to you, create an issue in this github! :)
