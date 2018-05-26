# change-poller
Utility for polling websites and notifying user on change events.

## Dependencies
`change-poller` uses Python 3 equipped with modules from standard libraries. They should be installed if not only minimal Python package is installed.

For getting web pages and elements at them, Selenium web browser automator with a webdriver for Python is used. Also, to not require display (and also not polluting existing displays), the Xvfb display server is used.

 * Python v3.5 or better (not tested with lower versions, may work on python3.2)
 * Pip (to install some Python dependencies)
 * A browser (Firefox is recommended as a default)
 * Webdriver for the browser (refer to [this manual](https://selenium-python.readthedocs.io/installation.html) to look for browser-specific instructions)
 * Xvfb (optional)

Instructions for Debian-based distros:

    apt-get install python3 python3-pip xvfb
    pip install selenium
    # Download and unpack your driver and put it in to your `$PATH` (`~/bin` is sufficient for local installs)

If you don't want to use Xvfb display server and still don't want to have Selenium window popping to your display, you could install PhantomJS webdriver instead of Firefox one. This is untested though.

## Installation
Make sure you have all the dependecies installed. This installs the program to local path. You should have `~/bin` already but if you don't, `mkdir` it.

    cd ~/bin
    wget https://github.com/Hegezcc/change-poller/raw/master/main.py -O change-poller
    chmod +x change-poller

Now you have `change-poller` in your local path. To install globally, just put the executable to the right place, e.g. `/usr/local/bin`. Remember to install your dependencies also globally.

## Usage
Simplified program flow:

 * parse arguments and load configuration
 * download the webpage
 * find the right element by CSS selector and get the text content from it
 * if regex is given, match it against the text content to get more fine-grained control about matches
 * check if the text content has changed from the last time
 * save changes to page-specific data file
 * do the four previous lines as long as there are more pages to process
 * notify user about possible changes

You can add pages by `--page URL SELECTOR [REGEX]`. Remember to add `--save-config` flag when adding persistent pages to check for them at every run. Please note that the `--help` message says that you can add many pages with one `--page` flag, this is false and a limitation of the argument parsing library we are using. Use a second `--page` to add a second entry to fetch list.

Remember to escape your arguments if they have spaces or shell characters (e.g. `&`).

CSS selectors reference: https://www.w3schools.com/cssref/css_selectors.asp
A good way for a newbie to get a grab on CSS selectors: https://stackoverflow.com/questions/17415141/generating-css-selector-in-firefox
Regex tutorial: https://www.regexone.com/
Regex debugger: https://regex101.com/

Note about pages: for now it's not possible to edit the page entries via command line once they are created. You can though get the configuration file path with `change-poller -P` and modify page entries from the config. Do not directly change the url, instead add a 'new_url' key alongside the 'url'. The change will be catched up when the program is run.

**Examples:**

    # Print to a log file (default is ~/.change-poller.log) when the first DuckDuckGo search result for asdf changes
    change-poller --page "https://duckduckgo.com/?q=asdf" "#r1-0 .result__extras__url" --event-list log
    
    # Get a notification and print to standard output when EUR <-> USD chart changes by tenths
    change-poller -p "https://www.xe.com/currencycharts/?from=EUR&to=USD&view=1D" "#rates_detail_desc strong:nth-of-type(2)" "\d.\d" -e notify -e print
    
    # Save some default settings (if saving or printing config, pages will not be fetched)
    change-poller --use-xvfb --event-list log --event-list notify --log-path /var/log/change-poller.log --save-config --print-config
    # That command could also use short arguments:
    change-poller -x -e log -e notify -l /var/log/change-poller.log -S -P
    
    # Show debug messages
    change-poller -vv
    
    # Add to crontab for maximum benefit
    (crontab -l ; echo "0 9 * * * change-poller") | crontab -

Get full usage info with `change-poller --help`.

## TODOs/ideas

 * Add a command to be run when a page changes or not
 * Make the `--page` option more obvious (or remove it completely and add a `ffmpeg`-like interpretation of input arguments)
 * Add lock files/keep file descriptors open to be sure that no race conditions occur
 * Allow more changes to be detected than only text, for example in the HTML content or screenshot of element
 * Allow for custom loggers
 * Allow events to be run also for different log level messages
 * Somehow check for user interactivity at computer and save notifications for later time if user is AFK
 * Create interactive interface for configuring (`-i` flag)
 * Create installer script
 * Add LICENSE
 * Create a (maybe distributable) blockchain mechanism to record the changes and modifications

Discussion in the form of issues, extending the above idea-list or even pull requests are welcome.
