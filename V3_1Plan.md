# Goals for V 3.1 update
the current version of the sender and the Arduino work well to create simple animated patterns and stream it to selected devices over wifi. For version 3.1 the focus is to expand the workflow to be able to design "Clips" using the existing interface, but then save them into a "Clip Library" where they can then be combined into triggerable timelines using the "Look Mixer". The "Look Controller" will be used to trigger looks during performance.

# Simplify Outputs
- Reduce number of outputs to 2. A0 , A1
- Keep the same output choices

# Live Clip Designer
This is similar to what the interface currently does. The notion is that this is where the components of looks can be prototyped.
- To add
This will need a 'Save Look' which will require naming. It should split the components into individual units, but be named conventionally. For example, let's say a prototyped look has 1 short strip and 1 grid. When a look is saved and the user calls it "LoadingAnim" the indidividual units should be called LoadingAnim_sStrip1, LoadingAnim_grid1. (They are numbered because there can be multiple of the same type).

# Clip Library
A visual interface to all of the saved looks. It should be a simple, open format that will allow them to be transferred between different machines. It should include
- simple visualization or thumbnail of the look. 
- Name of the look
- Output type: short strip, long strip, grid
- Key colors
- general effect used
- There should be methods for searching through the library and sorting by key component types.

# Look Mixer
This works as a simple timeline style interface that allows the creation of a 'Look'. A scene can have multiple 'Clips' combined and crosfaded together over time using this interface.
Constraints
-A scene should be defined by the number and type of outputs. For instance A0-grid, A1-short strip, A2-none. 
-It should have its own playback method once, loop, boomerang.
-Look Types should be draggable onto the timeline and also moved / scaled by dragging

This will be generated into the Look Controller essentially as a button that triggers the entire look. Consider that this is a theatre context and keep with those methods/tools

# Look Controller
The control panel for all of the looks that have been created. Each look thumbnail should have a clear main label and short description. The visual comparitor is a physical control panel.


# Other Factors
## Live Connection to Devices
Each specific mode: Clip Designer, Look Mixer, Look Controller will need to establish a live connection to one or more devices. Create a clear method for handling this connection between the different modes. 



## API Compliance
All the methods created should be done in a way that allows it to be replicated in other programming languages/tools, even if done in a different way. This main python tool is the fallback, but everything should be created in a way so that this can also be controlled via
- Isadora
- Touch Designer
- Processing (less important)
- three.js (less important)

# Buildout
- Create a distinct 'V3_1' folder for the new versions
- Put the current version inside a 'V3_0'
