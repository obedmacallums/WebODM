PluginsAPI.Map.willAddControls([
        'road/build/Road.js',
        'road/build/Road.css'
    ], function(args, Road){
    var tasks = [];
    var ids = {};

    for (var i = 0; i < args.tiles.length; i++){
        var task = args.tiles[i].meta.task;
        if (!ids[task.id]){
            tasks.push(task);
            ids[task.id] = true;
        }
    }

    if (tasks.length > 0){
        args.map.addControl(new Road({map: args.map, tasks: tasks, tiles: args.tiles}));
    }
});
