# Changes to update-photonotes

## TODOs and ideas
## May 2023
- update-db: implement sync/update of photo blogs
- ensure linking between photo blogs and photo notes
- refactoring of data model to differentiate images with notes and stacked images


## Features

### 0.8.2

### Features
- new action extract-enex
- new action reset-db
- database table flickr_image streamlined: removed fields see_info, need_cleanup and reference
- flickr_table, unique key extended to include guid_note 
to handle cases where same image link is associated with more than on e photo-note (occasionally happens)
- support both https://flickr.com and https://www.flickr.com style Flickr URLs

### Improvements
#### update-db
- detect and handle replaced notes (e.g. from cleanup of see-info)
- fix and improve handling of see-info detection (less false-positives)

### Fixes
- ignore deleted notes
- fix issue with note titles, encode ampersands to produce valid XML


### 0.8.1

### Features
- new action authenticate

### Improvements
#### create-note
- copy note tags from old photo-note
- use title from old photo-note, prepent '[new] '
- description with markup style links
flickr images to use Flickr session from authenticate when available

### Fixes
#### create-note
- ampersand in note and photo title now handled gracefully


### 0.8.0

### Features
- initial version
- Adapted from argparse to click
- Supported actions: create-note, update
