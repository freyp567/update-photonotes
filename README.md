# update-photonotes

Update my personal photo-notes from Flickr in Evernote.

## Description

update-photo0notes is a commandline based application that requires the backup database generated by evernote-backup, 
referred to in the following description as en_backup.db. It provides means to create an inventory of all photo-notes
found, validation and updateing (planned yet). 
It also supports creation of photo-notes generationg .enex files that can be easily imported to Evernote, that 
fulfill the requirements to be a photo-note that can be automatically detected and updated.

## Photo-notes

Here is a concrete example of one of my photo-notes. It is on an image that can be found on Flickr under
[Abyssinian Roller](https://www.flickr.com/photos/rod_waddington/49889542513/)

... and is one of the excellent pictures that are made available with a permissive license (Creative Commons)
so I picked this one for an example as I may share and adapt the image under the CC BY-SA 2.0 license set.

For this I will give a more detailled description on what update-photonotes action create-note can do - this will
also be type of notes that can be handled and (in future) updated by action update-db. Explanation of both follows. 
For the example see later on in section 
[What a photo-note looks like](https://github.com/freyp567/update-photonotes#what-a-photo-note-looks-like).


## Actions

update-photonotes currently provides  two actions:

### update-db

Extend the en_backup.db database by providing additional tables for inventory of the existing photo-notes in en_backup.db
and update them from Flickr.

The main issue with update is, that there needs to be a reliable way to identify the Flickr image a photo-note is 
relating to. A note may contain many HTML links (````<a href=...>```` Elements), but which one is the one identifying the image
described?

The update action has to rely on heuristics, I choose the following one:
First, every note must contain a line starting with "See: " and followed by a highlighted reference to the image.
Secondly, there must also be a HTML link for this image in the note, to be the last photo URL.

Currently I still am busy with the job to make all my photo-notes complient to these two rules.
Update currently scans all photo-notes tagged 'flickr-image' in en_backup.db and complains if the expectations are not met.
Sureley it takes some time to update all notes that do not fit, but I hope the result will be worth that effort.


### create-note

There are two variants of photo-notes: The basic one is self-contained, keeping all informatino on image and photo owner
in a single note. That is ok if there are one, two images from a specific owner, and used in these cases.

There is also an extended variant, where one note is on the photo-owner, a so-called blog note, 
ond several additional notes for each image I found of interest or worth taking a note for on separate notes.
The notes are linked, with the means of cross note linking supported by Evernote, with the blog note
containing a list of images, so it is easy to navigate from blog to image and back again.

The action create-note can create both variants. depending on the URL that is passed.
If it is https://www.flickr.com/people/(blog-id), then a blog note is created for it.
If it is https://www.flickr.com/photos/(blog-id)/(photo-id)/(optional-context), then a photo note will be 
created with the info on the photo owner respectiviy the blog on top. 

For time beeing converting a self-contained photo-note to one with blog / photo relationship is easy and not much work,
so there is no effort taken to differentiate that, but that may something I will change and improve in the future.


## Limitations

Use of the Flickr API is under some restrictions defined by the Agreements you have to confirm.
One of them is to limit the number of API calls per hour to be below 3.600 calls. So use the tool with care,
in spite of the attemts made to ensure that rate limit accessing the Flickr API stays below.

Also you will need your own Flickr API keys, but it should be easy to apply for and obtain them.
For details see [The App Garden](https://www.flickr.com/services/api/).

You will also need an up-to-date python environment, with poetry on board.
The documentation for poetry is here: 
[Poetry - Pyton dependency managenent and packaging made easyi](https://python-poetry.org/docs/#installing-with-the-official-installer).


## Background / Motivation

Since a couple of years I already collect notes on excellent and interesting photos (from flickr and beyond).
The notes are created using Evernote Webclipper, then adapted and enhaced by adding more content
and information that is essential to find the image again later on ... e.g. some location info,
if possible the introductory sentence from Wikipedia. And not to forget tagging, where I do not just want to take
the tags provided by the photo owners but put own effort in tagging, what produces a better quality and support tp 
search for images later on.

So focus was on how to create photo-notes and be able to search then efficiently. An Evernote is actually still 
my preferred tool for note-taking, because of the search functionality it provides.

But this manual note-taking approach has some drawbacks. The format produced by Webclipper is a starting point
but could be improved. Manual formatting the generated notes takes time and is (sometimes) tedious work, so 
my idea was to automate that and focus on the aspects to qualify the notes created to support searching.

Also, I found evernote-backup to be an excellent tool to make a backup of my Evernote notes, having them now as 
cached versions in a local SQLLite database that can be kept in sync easily, and gives the opportunity to access
the SQLLite database for inventory, validation and updating the photo-notes. That was the motivation
to create update-photonotes.

Note that it is a commandline based application that requires some (hopefully minimal) knowledgbe of Python to make
use of it. It still is under active development, as there are a couple of ideas I still want to implement and
improve.


## Usage example, create-note

Here a usage sample for the create-note action. 
Precondition is that you have your own Flickr API keys, and add it to a .env file (or the calling environment)
There are three environment variables that are required

DB_PATH=(your Path to ...)\evernote_backup_data
API_KEY=(your Flickr API key)
API_SECRET=(your Flickr API secret key)

note that DB_PATH must point to a directory where the en_backup.db has been create using evernote-backup
documentation can be found here
[evernote-backup](https://pypi.org/project/evernote-backup/)
and [vzhd1701/ evernote-backup](https://github.com/vzhd1701/evernote-backup)

With these variables properly defined, the action create-note can be invoked as follows
note: run it on a cmd.exe or Windows Terminal console, with current directory set to the project root dir
(may also run on macOS, I am sure, but currently I have non at hand so I cannot test it there)

Run from command line:

python.exe main.py create-note https://www.flickr.com/photos/rod_waddington/49889542513/in/datetaken/


This will produce the console output similar to that one:

```
2023-05-01 15:38:05,269 | [INFO] | 9748 | using evernote-backup db from F:\backup\Evernote\evernote_backup_data\en_backup.db
2023-05-01 15:38:05,269 | [INFO] | 9748 | creating photonote for photo from URL 'https://www.flickr.com/photos/rod_waddington/49889542513/in/datetaken/'
2023-05-01 15:38:05,269 | [INFO] | 9748 | authenticated using api_key='5d078f6c2d815c25891151b04782dd55'
2023-05-01 15:38:05,269 | [INFO] | 9748 | create photo-note from https://www.flickr.com/photos/rod_waddington/49889542513/in/datetaken/
2023-05-01 15:38:05,915 | [INFO] | 9748 | user for rod_waddington is 64607715@N05 / 'Rod Waddington' - #=11148
2023-05-01 15:38:06,550 | [WARNING] | 9748 | lookup image 49889542513 in photostream
2023-05-01 15:38:10,187 | [INFO] | 9748 | image found for 49889542513 at pos=2257
2023-05-01 15:38:10,187 | [INFO] | 9748 | found photo-note / image for rod_waddington|49889542513
2023-05-01 15:38:13,037 | [INFO] | 9748 | api cache stats:
cache hits / misses:
  _all: 3 / 14
  flickr.people.getInfo: 3 / 1
  flickr.people.getPhotos: 0 / 1
  flickr.photos.geo.getLocation: 0 / 1
  flickr.photos.getAllContexts: 0 / 1
  flickr.photos.getInfo: 0 / 2
  flickr.photos.search: 0 / 5
  flickr.photosets.getInfo: 0 / 2
  flickr.urls.lookupUser: 0 / 1

.
2023-05-01 15:38:13,037 | [INFO] | 9748 | created note in F:\backup\Evernote\evernote_backup_data\update_photonotes\import\rod_waddington 49889542513 .enex
2023-05-01 15:38:13,038 | [INFO] | 9748 | create_note completed.
```

Note that it is still an early stage of development (wrote this code in my spare time last week) so output may be 
still a little but verbose. I will strive to reduce and streamline it to what is of importance

You see that due to the use of CountingAPIcallsCache - 
it extens the (flickr_api´provided SimpleCache by cache hit/miss counting - we see that running create-note
costs 14 API calls (17 actually, but 3 of them are eliminated by the caching mechanism)

The number of API calls may depend on how far the Walker mechanism has to iterate over the photo stream to find the imag
specified by the photo id in the URL. If it is an older image, it may take more calls, and I did hardcode a limit of
5000 iamges, so if it is an odler image that is beyound that limit it may fail. Note that the photo stream of
Rod Waddington conains currently over 11.659 public photos, so it is just a question how far you want to reach back
in time to create notes from older photos. This limitation can be changed by setting --max-pos to a higher value,
do so if you need ... but keep in mind there is the requirement to keep the number of API calls per hour below
3.600 (see [The Flickr
Developer Guide: API](https://www.flickr.com/services/developer/api/), quoted: 
> API, Limits: 
  Since the Flickr API is quite easy to use, it's also quite easy to abuse, which threatens all services 
relying on the Flickr API. To help prevent this, we limit the access to the API per key. 
If your application stays under 3600 queries per hour across the whole key 
(which means the aggregate of all the users of your integration), you'll be fin)

So it is your responsibility to use the action in a manner as not to go beyond this limits.
My experience is that is ok to take a dozen of photo-notes in an hour. But still occasionally I 
have an eye on the statistics Flickr provides for my API key.

To conclude the example, the result is a .enex file (path shown on the last line of console output)
There is one additional step required: to import the .enex file into Evernote, what can be done by double-clicking
onto it on Windows.

So I provided the generated photo-note in the (yet to be written) test suite of update-photonotes,
see tests/data and file 'rod_waddington 49889542513 .enex'.

Note that I added whitespaces around the photo id by intent - so it is easier to pick it in the Windows explorer
and copy it to the clipboard, as you may search for the imported note in Evernote, best using this id.


## What a photo-note looks like

Note that the create-note action does only generate a basic note, that serves as starting point for qualifing it
by adding contents, tags and - indispensable for finding the image later on again - tags.

As I do note-taking with Evernote and Flickr already since a couple of years, there are some routines and
ways to enhance the notes intellectually that I did establish and improve during this time. I know that yours may
be different, but I am sure everyone that does large scale note-taking does it differently from how I do it.

Nethertheless here a sample of the note generated above, or rather the orginal note than I then do update 
by copying information generated in the newly imported note to the old note (in case it is a blot note) or
the otherway round, copy information from the old note to the new one, updating links and moving the old one to the bin.

The note given as sample looks as follows:
![photo-note_1.jpg](doc%2Fphoto-note_1.jpg)

Some notes before scrolling further down:
I try to combine similar images onto one photo-note.
This helps to keep the number of notes small, 
and still have the chance to find the image again because 
it can be found from the main or base image of the note.

So lets scroll further down ...
![photo-note_2.jpg](doc%2Fphoto-note_2.jpg)

I dare to admit, see the topmost comment: I used this image as background image
for Teams for a while - the image is under Creative Commons License, 
what should explicitly allow that.

And the photo-note has an image that is used as thumbnail in the 
list view of evernote. Also helpful to find it again.

Then some information on photo owner and license ...
we scroll down to the end and see:

![photo-note_3.jpg](doc%2Fphoto-note_3.jpg)

Here you wee the information copied from Wikipedia. 
Main reason also to assist fulltext search. And as my native language is german,
also some info in German, as the animal names tend to be quite different.
Still I prefer english, especially for landscape photos and location names
as it makes search easier so I have to search primarily for english names, only.

I hope that this illustrates the concept of a photo-note 
that is what the create-note action should help to create.
It does only create a basic version, but the remaining is 
anyway hard to automate and has to be completed manually.


## Searching

Tags are key for finding photo-notes. 
Choose them by design, with the question how and what you want to search in mind
and this is nothing that can be (easily) automated. Maybe KI will help in future, but it still is a way to go ...
and the KI does not know what and how I want to search

So back to the sample, I remember months (or years) later that I saw an interesting photo from an african bird.
I my search in evernote for it using e.g.

``tag:image tag:bird tag:Africa``

For given search term, my Evernote (with over 50.000 notes) returns 8 notes I can look through - 
and can find the photo I had in mind again.

Fortunately I am no ornithologist but my focus is more on landscape photography, but in case I were
(or wildlife photography focussed) I would have to tag my photo-notes differently or more specifically.

So my tip is to put the effort into the tagging of the photo-notes, and also enrich them e.g. by 
adding content from Wikipedia, at least the sections that are helpful for searching. 

Adding the first paragraph from the beginning, and the categories from the end of a wikipedia article
that describes a photo location (or nearby city, village or what else) helps to restrict searches ...
and also to find similar images more easily.
