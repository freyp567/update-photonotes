# Changes to update-photonotes

## TODOs and ideas
## May 2023
- update-db: implement sync/update of photo blogs
- ensure linking between photo blogs and photo notes
- refactoring of data model to differentiate images with notes and stacked images


## Features

### 0.8.2

### Improvements
#### update-db
- detect and handle  replaced notes (e.g. from cleanup of see-info)

### Fixes
- ignore deleted notes


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
